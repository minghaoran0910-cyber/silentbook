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

@router.get("/settings")
async def get_settings(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取所有设置（过滤敏感字段）"""
    settings = db.query(Setting).all()
    # 过滤掉密码哈希等敏感字段
    SENSITIVE_KEYS = {"auth_password", "auth_secret", "jwt_secret"}
    return {s.key: s.value for s in settings if s.key not in SENSITIVE_KEYS}


@router.put("/settings")
async def update_settings(items: dict, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """批量更新设置"""
    for key, value in items.items():
        existing = db.query(Setting).filter(Setting.key == key).first()
        if existing:
            existing.value = str(value)
        else:
            db.add(Setting(key=key, value=str(value)))
    db.commit()
    return {"status": "ok", "updated": len(items)}


@router.get("/settings/sources")
async def get_sources(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取通知源配置"""
    raw = db.query(Setting).filter(Setting.key == "notification_sources").first()
    if not raw or not raw.value:
        # 默认全部开启
        return {"cmb": True, "icbc": True, "ccb": True, "alipay": True, "wechat_pay": True}
    import json
    return json.loads(raw.value)


@router.put("/settings/sources")
async def update_sources(sources: dict, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """更新通知源配置"""
    import json
    existing = db.query(Setting).filter(Setting.key == "notification_sources").first()
    if existing:
        existing.value = json.dumps(sources)
    else:
        db.add(Setting(key="notification_sources", value=json.dumps(sources)))
    db.commit()
    return {"status": "ok"}


@router.get("/settings/agents")
async def get_agent_configs(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取 Agent 配置"""
    agents = db.query(AgentConfig).all()
    return [{
        "id": a.id, "name": a.name, "api_endpoint": a.api_endpoint,
        "is_active": a.is_active, "system_prompt": a.system_prompt or ""
    } for a in agents]


@router.put("/settings/agents/{agent_id}")
async def update_agent_config(agent_id: int, data: dict, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """更新 Agent 配置"""
    agent = db.query(AgentConfig).filter(AgentConfig.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if "is_active" in data:
        agent.is_active = data["is_active"]
    if "name" in data:
        agent.name = data["name"]
    if "api_endpoint" in data:
        agent.api_endpoint = data["api_endpoint"]
    if "system_prompt" in data:
        agent.system_prompt = data["system_prompt"]
    db.commit()
    return {"status": "ok"}


# ===== 现金流日历（V2-009）=====
