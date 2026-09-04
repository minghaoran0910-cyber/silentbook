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

@router.get("/assets", response_model=List[AssetResponse])
async def list_assets(
    asset_type: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """获取资产列表"""
    query = db.query(Asset)
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if status:
        query = query.filter(Asset.status == status)
    return query.order_by(Asset.updated_at.desc()).all()


@router.post("/assets", response_model=AssetResponse)
async def create_asset(asset: AssetCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """添加资产"""
    db_asset = Asset(**asset.model_dump())
    db.add(db_asset)
    db.commit()
    db.refresh(db_asset)
    return db_asset


@router.put("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: int,
    asset_update: AssetUpdate,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """更新资产"""
    db_asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not db_asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    
    update_data = asset_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_asset, key, value)
    db_asset.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_asset)
    return db_asset


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """删除资产"""
    db_asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not db_asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    db.delete(db_asset)
    db.commit()
    return {"message": "已删除"}



# ===== 黄金实时价格 =====


@router.get("/gold-price")
async def get_gold_price():
    """获取实时黄金价格（元/克），数据来自上海金交所"""
    import time as _time
    
    # 缓存 5 分钟
    cache_key = "_gold_price_cache"
    now = _time.time()
    if hasattr(app, cache_key):
        cached = getattr(app, cache_key)
        if now - cached["ts"] < 300:
            return cached["data"]
    
    price = None
    source = ""
    
    # 数据源1: 新浪财经（上海金交所 Au99.99）
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://hq.sinajs.cn/?list=au0",
                headers={"Referer": "https://finance.sina.com.cn"}
            )
            text = resp.text.strip()
            if "=" in text:
                data_part = text.split("=")[1].strip('"').split(",")
                if len(data_part) > 3:
                    price = float(data_part[3])
                    source = "上海金交所 Au99.99"
    except Exception:
        pass
    
    # 数据源2: 国际金价换算（备用）
    if not price:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("https://api.gold-api.com/price/XAU")
                data = resp.json()
                if "price" in data:
                    usd_per_oz = data["price"]
                    # 盎司转克，美元转人民币（近似汇率）
                    price = round(usd_per_oz / 31.1035 * 7.2, 2)
                    source = "国际金价(换算)"
        except Exception:
            pass
    
    if price:
        result = {
            "price": price,
            "unit": "元/克",
            "source": source,
            "updated_at": datetime.now().isoformat()
        }
        setattr(app, cache_key, {"data": result, "ts": now})
        return result
    
    raise HTTPException(status_code=503, detail="暂时无法获取金价，请稍后重试")

# ===== 负债管理 =====


@router.get("/liabilities", response_model=List[LiabilityResponse])
async def list_liabilities(
    liability_type: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """获取负债列表"""
    query = db.query(Liability)
    if liability_type:
        query = query.filter(Liability.liability_type == liability_type)
    if status:
        query = query.filter(Liability.status == status)
    return query.order_by(Liability.updated_at.desc()).all()


@router.post("/liabilities", response_model=LiabilityResponse)
async def create_liability(liability: LiabilityCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """添加负债"""
    db_liability = Liability(**liability.model_dump())
    db.add(db_liability)
    db.commit()
    db.refresh(db_liability)
    return db_liability


@router.put("/liabilities/{liability_id}", response_model=LiabilityResponse)
async def update_liability(
    liability_id: int,
    liability_update: LiabilityUpdate,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """更新负债"""
    db_liability = db.query(Liability).filter(Liability.id == liability_id).first()
    if not db_liability:
        raise HTTPException(status_code=404, detail="负债不存在")
    
    update_data = liability_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_liability, key, value)
    db_liability.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_liability)
    return db_liability


@router.delete("/liabilities/{liability_id}")
async def delete_liability(liability_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """删除负债"""
    db_liability = db.query(Liability).filter(Liability.id == liability_id).first()
    if not db_liability:
        raise HTTPException(status_code=404, detail="负债不存在")
    db.delete(db_liability)
    db.commit()
    return {"message": "已删除"}


# ===== 负债清单增强（V2-011）=====

# 负债类型中文标签


LIABILITY_TYPE_LABELS = {
    "mortgage": "房贷",
    "car_loan": "车贷",
    "credit_card": "信用卡",
    "credit_card_installment": "信用卡分期",
    "huabei": "花呗",
    "baitiao": "白条",
    "loan": "其他贷款",
    "other": "其他",
}

# 负债类型默认优先级排序
LIABILITY_TYPE_ORDER = [
    "mortgage", "car_loan", "credit_card", "credit_card_installment",
    "huabei", "baitiao", "loan", "other"
]


@router.get("/liabilities/summary")
async def get_liabilities_summary(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """负债清单汇总：按类型分组统计 + 总体概览"""
    liabilities = db.query(Liability).all()
    
    # 按类型分组
    by_type = {}
    for lt in LIABILITY_TYPE_ORDER:
        by_type[lt] = {
            "label": LIABILITY_TYPE_LABELS[lt],
            "items": [],
            "total_amount": 0,
            "current_amount": 0,
            "monthly_payment": 0,
            "count": 0,
            "active_count": 0,
        }
    
    total_current = 0
    total_monthly_payment = 0
    total_interest_estimate = 0
    status_counts = {"active": 0, "paid": 0, "overdue": 0}
    
    for liab in liabilities:
        lt = liab.liability_type if liab.liability_type in by_type else "other"
        entry = by_type[lt]
        entry["items"].append({
            "id": liab.id,
            "name": liab.name,
            "total_amount": liab.total_amount,
            "current_amount": liab.current_amount,
            "interest_rate": liab.interest_rate,
            "monthly_payment": liab.monthly_payment,
            "remaining_periods": liab.remaining_periods,
            "due_date": str(liab.due_date) if liab.due_date else None,
            "status": liab.status,
            "notes": liab.notes,
        })
        entry["total_amount"] += liab.total_amount
        entry["current_amount"] += liab.current_amount
        entry["monthly_payment"] += liab.monthly_payment or 0
        entry["count"] += 1
        if liab.status == "active":
            entry["active_count"] += 1
        
        total_current += liab.current_amount
        total_monthly_payment += liab.monthly_payment or 0
        # 估算总利息 = 月供 × 剩余期数 - 当前待还
        if liab.monthly_payment and liab.remaining_periods:
            total_interest_estimate += liab.monthly_payment * liab.remaining_periods - liab.current_amount
        
        if liab.status in status_counts:
            status_counts[liab.status] += 1
    
    # 清除空类型
    by_type = {k: v for k, v in by_type.items() if v["count"] > 0}
    
    return {
        "total_current_amount": round(total_current, 2),
        "total_monthly_payment": round(total_monthly_payment, 2),
        "total_interest_estimate": round(max(total_interest_estimate, 0), 2),
        "status_counts": status_counts,
        "total_count": len(liabilities),
        "by_type": by_type,
    }


@router.get("/liabilities/debt-ratio")
async def get_debt_ratio(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """负债率监控：月还款额 / 月收入，超过 40% 预警"""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # 本月收入
    monthly_income = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.transaction_type == "income",
        Transaction.parsed_at >= month_start
    ).scalar() or 0.0
    
    # 活跃负债的月供总额
    active_liabilities = db.query(Liability).filter(Liability.status == "active").all()
    total_monthly_payment = sum(l.monthly_payment or 0 for l in active_liabilities)
    total_current_amount = sum(l.current_amount for l in active_liabilities)
    
    # 计算负债率
    debt_ratio = (total_monthly_payment / monthly_income * 100) if monthly_income > 0 else 0
    
    # 预警级别
    DEBT_RATIO_THRESHOLD = 40  # 40% 预警线
    if monthly_income == 0:
        alert_level = "unknown"
        alert_message = "本月无收入数据，无法计算负债率"
    elif debt_ratio < 30:
        alert_level = "safe"
        alert_message = "负债率健康"
    elif debt_ratio < DEBT_RATIO_THRESHOLD:
        alert_level = "notice"
        alert_message = "负债率偏高，建议关注"
    elif debt_ratio < 60:
        alert_level = "warning"
        alert_message = "负债率超过 40% 预警线，建议优化债务结构"
    else:
        alert_level = "critical"
        alert_message = "负债率严重过高，存在财务风险"
    
    # 按类型分组的月供
    by_type = {}
    for l in active_liabilities:
        lt = LIABILITY_TYPE_LABELS.get(l.liability_type, l.liability_type)
        if lt not in by_type:
            by_type[lt] = {"monthly_payment": 0, "current_amount": 0, "count": 0}
        by_type[lt]["monthly_payment"] += l.monthly_payment or 0
        by_type[lt]["current_amount"] += l.current_amount
        by_type[lt]["count"] += 1
    
    return {
        "monthly_income": round(monthly_income, 2),
        "total_monthly_payment": round(total_monthly_payment, 2),
        "total_current_debt": round(total_current_amount, 2),
        "debt_ratio": round(debt_ratio, 1),
        "threshold": DEBT_RATIO_THRESHOLD,
        "alert_level": alert_level,
        "alert_message": alert_message,
        "is_over_threshold": debt_ratio >= DEBT_RATIO_THRESHOLD,
        "by_type": {k: {**v, "monthly_payment": round(v["monthly_payment"], 2), "current_amount": round(v["current_amount"], 2)} for k, v in by_type.items()},
        "active_liability_count": len(active_liabilities),
    }


# ===== 还款计划（V2-012）=====


def _add_months(dt: datetime, months: int) -> datetime:
    """简单月份加法，不依赖 dateutil"""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, 28)  # 避免月末溢出
    return dt.replace(year=year, month=month, day=day)


@router.get("/liabilities/{liability_id}/repayment-plan")
async def get_repayment_plan(liability_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """还款计划：每期金额/利息/本金/余额 + 总利息 + 预计还清日期"""
    liability = db.query(Liability).filter(Liability.id == liability_id).first()
    if not liability:
        raise HTTPException(status_code=404, detail="负债不存在")
    if liability.status == "paid":
        return {"schedule": [], "total_interest": 0, "total_payment": 0,
                "remaining_periods": 0, "payoff_date": None, "message": "该负债已还清"}
    
    current = liability.current_amount or 0
    monthly_payment = liability.monthly_payment or 0
    remaining_periods = liability.remaining_periods or 0
    monthly_rate = (liability.interest_rate or 0) / 12 / 100
    
    if current <= 0 or remaining_periods <= 0 or monthly_payment <= 0:
        return {"schedule": [], "total_interest": 0, "total_payment": 0,
                "remaining_periods": 0, "payoff_date": None,
                "message": "当前余额、月供或剩余期数为0，无法生成还款计划"}
    
    # 检查月供是否足以覆盖首月利息
    first_month_interest = current * monthly_rate
    if monthly_payment <= first_month_interest and monthly_rate > 0:
        return {"error": "月供不足以覆盖月利息，无法生成还款计划",
                "monthly_payment": monthly_payment,
                "first_month_interest": round(first_month_interest, 2)}
    
    schedule = []
    total_interest = 0.0
    total_payment = 0.0
    balance = current
    
    for period in range(1, remaining_periods + 1):
        interest = round(balance * monthly_rate, 2)
        principal = round(monthly_payment - interest, 2)
        
        # 最后一期或余额不足以支撑完整月供：清零余额
        if period == remaining_periods or principal >= balance:
            principal = round(balance, 2)
            payment = round(principal + interest, 2)
        else:
            payment = round(monthly_payment, 2)
        
        balance = round(balance - principal, 2)
        total_interest += interest
        total_payment += payment
        
        schedule.append({
            "period": period,
            "payment": payment,
            "principal": principal,
            "interest": interest,
            "balance": max(balance, 0),
            "date": _add_months(datetime.utcnow(), period).strftime("%Y-%m-%d"),
        })
        
        if balance <= 0:
            break
    
    payoff_date = _add_months(datetime.utcnow(), len(schedule)).strftime("%Y-%m-%d")
    
    return {
        "liability_id": liability_id,
        "liability_name": liability.name,
        "liability_type": liability.liability_type,
        "schedule": schedule,
        "total_interest": round(total_interest, 2),
        "total_payment": round(total_payment, 2),
        "total_principal": round(current, 2),
        "remaining_periods": len(schedule),
        "monthly_payment": monthly_payment,
        "current_amount": current,
        "annual_interest_rate": liability.interest_rate or 0,
        "payoff_date": payoff_date,
    }


# ===== 设置 =====
