import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks, UploadFile, File, Header
from pydantic import BaseModel, Field
from sqlalchemy import func, case, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal, Transaction, AnalysisResult, Asset, Liability, AgentConfig, Setting, User, Account, Transfer, BackupRecord, FinancialGoal, GoalContribution, RecurringTransaction, init_db, SyncLog, WebhookEvent, Position, TradeRecord
from ..schemas import (
    TransactionCreate, TransactionUpdate, TransactionResponse,
    AnalysisResponse, DashboardStats,
    AssetCreate, AssetUpdate, AssetResponse,
    LiabilityCreate, LiabilityUpdate, LiabilityResponse,
    AccountCreate, AccountUpdate, AccountResponse, AccountTransfer, TransferResponse,
    GoalCreate, GoalUpdate, GoalResponse, GoalContributionCreate, GoalContributionResponse, GoalSummaryResponse,
    RecurringTransactionCreate, RecurringTransactionUpdate, RecurringTransactionResponse,
    RecurringSummaryResponse, AutoDetectResponse
)
from ..auth import require_user
from ..tenant import set_tenant_user_id, reset_tenant_user_id
from ..notification_push import pusher
from ..backup_crypto import read_backup, write_backup
from ..logging_config import setup_logging, log_buffer, generate_request_id, set_request_context
from .deps import (
    AGENT_API_URL, PARSER_API_URL, OPENCLAW_GATEWAY_URL,
    PLATFORM_ACCOUNT_MAP, LOW_BALANCE_THRESHOLD,
    ALERT_LEVELS, DEFAULT_ALERT_THRESHOLDS,
    LEVEL_LABELS, LEVEL_COMPRESSIBILITY, DEFAULT_CATEGORY_LEVELS,
    _update_account_balance, _check_low_balance_alert,
    _webhook_item_hash, _is_duplicate_body, _is_placeholder_analysis,
    get_alert_level, get_category_level,
)

router = APIRouter()

logger = logging.getLogger("silentbook")

BUDGET_LEVELS = {"L1", "L2", "L3"}


class BudgetCreate(BaseModel):
    category: str
    monthly_limit: float
    alert_threshold: float = 0.8  # 向后兼容，单个阈值
    level: str = Field("L2", pattern="^(L1|L2|L3)$")
    alert_thresholds: Optional[List[float]] = None  # 五级预警自定义阈值（4个上界值）

class BudgetResponse(BaseModel):
    id: int
    category: str
    monthly_limit: float
    alert_threshold: float
    level: str
    current_spent: float
    usage_rate: float
    class Config:
        from_attributes = True

# 预算存储在 Setting 表中（JSON 格式）


@router.get("/budgets", response_model=List[dict])
async def get_budgets(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取所有预算"""
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if not raw or not raw.value:
        return []
    
    import json
    budgets = json.loads(raw.value)
    
    # 计算当月已花
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    result = []
    for b in budgets:
        spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.category == b["category"],
            Transaction.transaction_type == "expense",
            Transaction.parsed_at >= month_start
        ).scalar() or 0.0
        
        usage = float(spent) / b["monthly_limit"] if b["monthly_limit"] > 0 else 0
        custom_ts = b.get("alert_thresholds")
        alert_info = get_alert_level(usage, custom_ts)
        result.append({
            **b,
            "current_spent": round(float(spent), 2),
            "usage_rate": round(usage * 100, 1),
            "alert": usage >= b.get("alert_threshold", 0.8),
            "alert_level": alert_info["level"],
            "alert_name": alert_info["name"],
            "alert_color": alert_info["color"],
        })
    return result


@router.get("/budgets/levels")
async def get_budgets_by_level(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """三级分类预算汇总：L1必要/L2改善/L3非必要"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    budgets = json.loads(raw.value) if raw and raw.value else []
    
    # 补全 level 字段（兼容旧数据）
    for b in budgets:
        if "level" not in b:
            b["level"] = DEFAULT_CATEGORY_LEVELS.get(b.get("category", ""), "L2")
    
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # 查本月所有支出
    month_txs = db.query(Transaction).filter(
        Transaction.transaction_type == "expense",
        Transaction.parsed_at >= month_start
    ).all()
    
    # 按分类汇总实际支出
    actual_by_category = {}
    for tx in month_txs:
        cat = tx.category or "其他"
        actual_by_category[cat] = actual_by_category.get(cat, 0) + tx.amount
    
    levels_data = {}
    for level in ["L1", "L2", "L3"]:
        level_budgets = [b for b in budgets if b.get("level") == level]
        budget_total = sum(b["monthly_limit"] for b in level_budgets)
        
        # 已设预算分类的支出
        budgeted_spent = 0
        items = []
        for b in level_budgets:
            spent = actual_by_category.get(b["category"], 0)
            budgeted_spent += spent
            usage = spent / b["monthly_limit"] if b["monthly_limit"] > 0 else 0
            alert_info = get_alert_level(usage, b.get("alert_thresholds"))
            items.append({
                "category": b["category"],
                "monthly_limit": b["monthly_limit"],
                "current_spent": round(spent, 2),
                "usage_rate": round(usage * 100, 1),
                "alert_threshold": b.get("alert_threshold", 0.8),
                "alert": usage >= b.get("alert_threshold", 0.8),
                "alert_level": alert_info["level"],
                "alert_name": alert_info["name"],
                "alert_color": alert_info["color"],
            })
        
        # 未设预算但属于该级别的分类支出
        budgeted_cats = {b["category"] for b in level_budgets}
        unbudgeted_spent = 0
        for cat, amt in actual_by_category.items():
            if cat not in budgeted_cats:
                cat_level = DEFAULT_CATEGORY_LEVELS.get(cat, "L2")
                if cat_level == level:
                    unbudgeted_spent += amt
        
        total_spent = budgeted_spent + unbudgeted_spent
        levels_data[level] = {
            "label": LEVEL_LABELS[level],
            "compressibility": LEVEL_COMPRESSIBILITY[level],
            "budget_total": round(budget_total, 2),
            "spent_total": round(total_spent, 2),
            "budgeted_spent": round(budgeted_spent, 2),
            "unbudgeted_spent": round(unbudgeted_spent, 2),
            "usage_rate": round(total_spent / budget_total * 100, 1) if budget_total > 0 else 0,
            "items": items,
        }
    
    return {
        "total_budget": round(sum(b["monthly_limit"] for b in budgets), 2),
        "total_spent": round(sum(v["spent_total"] for v in levels_data.values()), 2),
        "levels": levels_data,
    }


@router.get("/budgets/alerts")
async def get_budget_alerts(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """五级预警状态：返回每个预算的预警级别"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if not raw or not raw.value:
        return {"alerts": [], "summary": {"safe": 0, "normal": 0, "notice": 0, "over": 0, "critical": 0}}

    budgets = json.loads(raw.value)
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    alerts = []
    summary = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for b in budgets:
        spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.category == b["category"],
            Transaction.transaction_type == "expense",
            Transaction.parsed_at >= month_start
        ).scalar() or 0.0

        usage = float(spent) / b["monthly_limit"] if b["monthly_limit"] > 0 else 0
        alert_info = get_alert_level(usage, b.get("alert_thresholds"))
        summary[alert_info["level"]] += 1
        alerts.append({
            "category": b["category"],
            "monthly_limit": b["monthly_limit"],
            "current_spent": round(float(spent), 2),
            "usage_rate": round(usage * 100, 1),
            "alert_level": alert_info["level"],
            "alert_name": alert_info["name"],
            "alert_color": alert_info["color"],
            "level": b.get("level", DEFAULT_CATEGORY_LEVELS.get(b.get("category", ""), "L2")),
        })

    return {
        "alerts": alerts,
        "summary": {
            "safe": summary[1],
            "normal": summary[2],
            "notice": summary[3],
            "over": summary[4],
            "critical": summary[5],
        },
    }


@router.post("/budgets")
async def create_budget(budget: BudgetCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """创建/更新预算"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if raw:
        budgets = json.loads(raw.value)
    else:
        budgets = []
    
    # 检查是否已存在该分类的预算
    existing = next((b for b in budgets if b["category"] == budget.category), None)
    if existing:
        existing["monthly_limit"] = budget.monthly_limit
        existing["alert_threshold"] = budget.alert_threshold
        if budget.alert_thresholds:
            existing["alert_thresholds"] = budget.alert_thresholds
    else:
        budgets.append(budget.model_dump())
    
    if raw:
        raw.value = json.dumps(budgets)
    else:
        db.add(Setting(key="budgets", value=json.dumps(budgets)))
    db.commit()
    return {"status": "ok", "budgets": budgets}


@router.delete("/budgets/{category}")
async def delete_budget(category: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """删除预算"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if not raw:
        raise HTTPException(status_code=404, detail="无预算数据")
    
    budgets = json.loads(raw.value)
    budgets = [b for b in budgets if b["category"] != category]
    raw.value = json.dumps(budgets)
    db.commit()
    return {"status": "ok", "remaining": len(budgets)}


# ===== 预算模板（V2-008）=====
# 三套预设模板：节俭型/均衡型/宽松型
# 每套模板包含 L1/L2/L3 三级分类的月度预算


BUDGET_TEMPLATES = {
    "frugal": {
        "name": "节俭型",
        "description": "必要支出为主，压缩改善和非必要支出",
        "monthly_total": 4750,
        "budgets": [
            # L1 必要支出
            {"category": "房租", "monthly_limit": 2500, "level": "L1", "alert_threshold": 0.9},
            {"category": "餐饮", "monthly_limit": 1000, "level": "L1", "alert_threshold": 0.9},
            {"category": "交通", "monthly_limit": 200, "level": "L1", "alert_threshold": 0.9},
            {"category": "水电", "monthly_limit": 150, "level": "L1", "alert_threshold": 0.9},
            {"category": "话费", "monthly_limit": 50, "level": "L1", "alert_threshold": 0.9},
            {"category": "日用", "monthly_limit": 150, "level": "L1", "alert_threshold": 0.9},
            # L2 改善支出
            {"category": "学习", "monthly_limit": 200, "level": "L2", "alert_threshold": 0.8},
            {"category": "社交", "monthly_limit": 100, "level": "L2", "alert_threshold": 0.8},
            # L3 非必要支出
            {"category": "娱乐", "monthly_limit": 100, "level": "L3", "alert_threshold": 0.8},
            {"category": "购物", "monthly_limit": 300, "level": "L3", "alert_threshold": 0.8},
        ],
    },
    "balanced": {
        "name": "均衡型",
        "description": "必要支出充裕，改善支出合理，适度非必要支出",
        "monthly_total": 8400,
        "budgets": [
            # L1 必要支出
            {"category": "房租", "monthly_limit": 3500, "level": "L1", "alert_threshold": 0.9},
            {"category": "餐饮", "monthly_limit": 2000, "level": "L1", "alert_threshold": 0.9},
            {"category": "交通", "monthly_limit": 400, "level": "L1", "alert_threshold": 0.9},
            {"category": "水电", "monthly_limit": 300, "level": "L1", "alert_threshold": 0.9},
            {"category": "话费", "monthly_limit": 100, "level": "L1", "alert_threshold": 0.9},
            {"category": "日用", "monthly_limit": 300, "level": "L1", "alert_threshold": 0.9},
            # L2 改善支出
            {"category": "健身", "monthly_limit": 300, "level": "L2", "alert_threshold": 0.8},
            {"category": "学习", "monthly_limit": 300, "level": "L2", "alert_threshold": 0.8},
            {"category": "社交", "monthly_limit": 300, "level": "L2", "alert_threshold": 0.8},
            {"category": "咖啡", "monthly_limit": 200, "level": "L2", "alert_threshold": 0.8},
            # L3 非必要支出
            {"category": "娱乐", "monthly_limit": 200, "level": "L3", "alert_threshold": 0.8},
            {"category": "购物", "monthly_limit": 300, "level": "L3", "alert_threshold": 0.8},
            {"category": "旅游", "monthly_limit": 200, "level": "L3", "alert_threshold": 0.8},
        ],
    },
    "loose": {
        "name": "宽松型",
        "description": "各层级充裕，不刻意压缩非必要支出",
        "monthly_total": 14300,
        "budgets": [
            # L1 必要支出
            {"category": "房租", "monthly_limit": 5000, "level": "L1", "alert_threshold": 0.9},
            {"category": "餐饮", "monthly_limit": 3500, "level": "L1", "alert_threshold": 0.9},
            {"category": "交通", "monthly_limit": 800, "level": "L1", "alert_threshold": 0.9},
            {"category": "水电", "monthly_limit": 500, "level": "L1", "alert_threshold": 0.9},
            {"category": "话费", "monthly_limit": 200, "level": "L1", "alert_threshold": 0.9},
            {"category": "日用", "monthly_limit": 500, "level": "L1", "alert_threshold": 0.9},
            # L2 改善支出
            {"category": "健身", "monthly_limit": 500, "level": "L2", "alert_threshold": 0.8},
            {"category": "学习", "monthly_limit": 500, "level": "L2", "alert_threshold": 0.8},
            {"category": "社交", "monthly_limit": 500, "level": "L2", "alert_threshold": 0.8},
            {"category": "咖啡", "monthly_limit": 500, "level": "L2", "alert_threshold": 0.8},
            # L3 非必要支出
            {"category": "娱乐", "monthly_limit": 500, "level": "L3", "alert_threshold": 0.8},
            {"category": "购物", "monthly_limit": 800, "level": "L3", "alert_threshold": 0.8},
            {"category": "旅游", "monthly_limit": 500, "level": "L3", "alert_threshold": 0.8},
        ],
    },
}


@router.get("/budgets/templates")
async def list_budget_templates(user: User = Depends(require_user)):
    """列出所有预算模板"""
    result = []
    for key, tpl in BUDGET_TEMPLATES.items():
        level_summary = {"L1": 0, "L2": 0, "L3": 0}
        for b in tpl["budgets"]:
            level_summary[b["level"]] += b["monthly_limit"]
        result.append({
            "key": key,
            "name": tpl["name"],
            "description": tpl["description"],
            "monthly_total": tpl["monthly_total"],
            "category_count": len(tpl["budgets"]),
            "level_summary": level_summary,
        })
    return result


@router.get("/budgets/templates/{template_key}")
async def get_budget_template(template_key: str, user: User = Depends(require_user)):
    """获取某个预算模板的详情"""
    if template_key not in BUDGET_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"模板 '{template_key}' 不存在，可选: {', '.join(BUDGET_TEMPLATES.keys())}")
    tpl = BUDGET_TEMPLATES[template_key]
    return {
        "key": template_key,
        "name": tpl["name"],
        "description": tpl["description"],
        "monthly_total": tpl["monthly_total"],
        "budgets": tpl["budgets"],
    }


@router.post("/budgets/templates/{template_key}/apply")
async def apply_budget_template(template_key: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """应用预算模板 — 替换现有所有预算"""
    import json
    if template_key not in BUDGET_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"模板 '{template_key}' 不存在，可选: {', '.join(BUDGET_TEMPLATES.keys())}")

    tpl = BUDGET_TEMPLATES[template_key]
    budgets_data = [b.copy() for b in tpl["budgets"]]
    # 补全 alert_thresholds 为 None（使用默认五级预警）
    for b in budgets_data:
        b.setdefault("alert_thresholds", None)

    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if raw:
        raw.value = json.dumps(budgets_data)
    else:
        db.add(Setting(key="budgets", value=json.dumps(budgets_data)))
    db.commit()

    return {
        "status": "ok",
        "template": template_key,
        "template_name": tpl["name"],
        "applied_count": len(budgets_data),
        "monthly_total": tpl["monthly_total"],
        "budgets": budgets_data,
    }


# ===== Agent 分析 =====
