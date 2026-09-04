import logging
import os
import random
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
    get_alert_level, get_category_level, normalize_account_name,
)

router = APIRouter()

logger = logging.getLogger("silentbook")


# ===== 演示数据（一键载入/状态查询，仅限空库）=====
# 给新用户/推广体验用：仿真 3 个月中文商户流水 + 资产 + 预算 + 目标。
# 安全阀：库里已有任何交易就拒绝载入（一句话：只给白纸用）；
# 清除走 DELETE /transactions?confirm=true（余额同步回滚）。

# (分类, 商户池, 单笔区间, 频率权重)
_DEMO_TEMPLATES = [
    ("餐饮", ["星巴克", "瑞幸咖啡", "海底捞", "美团外卖", "肯德基", "喜茶"], (12, 180), 22),
    ("交通", ["滴滴出行", "地铁", "加油站", "停车费"], (8, 120), 12),
    ("购物", ["淘宝", "京东", "盒马", "拼多多"], (30, 600), 8),
    ("娱乐", ["电影院", "B站大会员", "健身房"], (15, 300), 4),
    ("生活", ["水电燃气", "话费充值", "物业费"], (50, 400), 3),
    ("医疗", ["药房", "体检中心"], (40, 500), 1),
    ("教育", ["买书", "在线课程"], (30, 400), 1),
    ("金融", ["信用卡还款", "基金定投"], (500, 3000), 2),
]
_DEMO_ACCOUNTS = ["招商银行", "支付宝", "微信"]
_DEMO_DAYS = 90


def _demo_status(db: Session) -> dict:
    n = db.query(Transaction).count()
    demo = db.query(Setting).filter(Setting.key == "demo_seed").first()
    return {"seeded": demo is not None, "transaction_count": n,
            "seeded_at": demo.value if demo and demo.value else ""}


@router.get("/demo/status")
async def demo_status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """演示数据状态：是否载入过、当前交易数。"""
    return _demo_status(db)


@router.post("/demo/seed")
async def demo_seed(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """载入 3 个月仿真演示数据。仅空库可用，否则 409。"""
    if db.query(Transaction).count() > 0:
        raise HTTPException(status_code=409, detail="库里已有交易数据，演示数据只给空库用；先清空再试")
    rng = random.Random(20260905)
    now = datetime.utcnow()
    rows = []
    for day_ago in range(_DEMO_DAYS, 0, -1):
        day = now - timedelta(days=day_ago)
        # 每日 1-4 笔，按权重抽模板
        for _ in range(rng.randint(1, 4)):
            bag = []
            for cat, merchants, span, w in _DEMO_TEMPLATES:
                bag += [(cat, merchants, span)] * w
            cat, merchants, span = rng.choice(bag)
            amount = round(rng.uniform(*span), 2)
            ts = day.replace(hour=rng.randint(7, 22), minute=rng.randint(0, 59))
            rows.append(Transaction(
                amount=amount, category=cat,
                account=rng.choice(_DEMO_ACCOUNTS),
                description=rng.choice(merchants),
                transaction_type="expense", confidence=1.0, parsed_at=ts,
            ))
        # 每月 5 号发工资
        if day.day == 5:
            rows.append(Transaction(
                amount=15000.0, category="工资", account="招商银行",
                description="月度工资", transaction_type="income",
                confidence=1.0, parsed_at=day.replace(hour=9, minute=0),
            ))
        # 每月 1 号交房租
        if day.day == 1:
            rows.append(Transaction(
                amount=3500.0, category="生活", account="招商银行",
                description="房租", transaction_type="expense",
                confidence=1.0, parsed_at=day.replace(hour=10, minute=0),
            ))
    db.add_all(rows)

    db.add_all([
        Asset(name="现金", asset_type="cash", current_value=8000,
              initial_value=8000, status="active"),
        Asset(name="招商银行储蓄", asset_type="savings", account="招商银行",
              current_value=120000, initial_value=100000, status="active"),
        Asset(name="沪深300ETF", asset_type="fund", account="证券账户",
              current_value=30000, initial_value=28000, status="active"),
        Liability(name="信用卡", liability_type="credit_card",
                  total_amount=10000, current_amount=3500,
                  monthly_payment=3500, status="active"),
        FinancialGoal(name="旅行基金", goal_type="savings",
                      target_amount=20000, current_amount=6500,
                      priority="medium", status="active"),
    ])
    import json
    db.add(Setting(key="budgets", value=json.dumps([
        {"category": "餐饮", "monthly_limit": 2000,
         "alert_threshold": 0.8, "level": "L2"},
        {"category": "交通", "monthly_limit": 800,
         "alert_threshold": 0.8, "level": "L1"},
        {"category": "购物", "monthly_limit": 3000,
         "alert_threshold": 0.8, "level": "L3"},
    ])))
    db.add(Setting(key="demo_seed", value=now.isoformat()))
    db.commit()
    return {"status": "ok", "imported_transactions": len(rows),
            "message": f"已载入演示数据：{len(rows)} 笔交易 + 资产/预算/目标"}
