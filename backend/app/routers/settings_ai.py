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

class AIConfigUpdate(BaseModel):
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None


@router.get("/settings/ai-config")
async def get_ai_config(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取用户自定义 AI 配置"""
    raw = db.query(Setting).filter(Setting.key == "ai_config").first()
    if raw and raw.value:
        import json
        config = json.loads(raw.value)
        # 隐藏 API Key（只返回前4位和后4位）
        if config.get("api_key"):
            key = config["api_key"]
            config["api_key_masked"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
        return config
    return {"api_base": "", "api_key": "", "api_key_masked": "", "model_name": ""}


@router.put("/settings/ai-config")
async def update_ai_config(config: AIConfigUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """更新用户自定义 AI 配置"""
    import json
    raw = db.query(Setting).filter(Setting.key == "ai_config").first()
    
    existing = {}
    if raw and raw.value:
        existing = json.loads(raw.value)
    
    if config.api_base is not None:
        existing["api_base"] = config.api_base
    if config.api_key is not None:
        existing["api_key"] = config.api_key  # 前端传完整 key，后端存储
    if config.model_name is not None:
        existing["model_name"] = config.model_name
    
    if raw:
        raw.value = json.dumps(existing)
    else:
        db.add(Setting(key="ai_config", value=json.dumps(existing)))
    db.commit()
    
    # 返回时隐藏完整 key
    result = existing.copy()
    if result.get("api_key"):
        key = result["api_key"]
        result["api_key_masked"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
        del result["api_key"]
    return result


@router.post("/settings/ai-config/test")
async def test_ai_config(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """测试 AI 配置是否可用"""
    import json
    raw = db.query(Setting).filter(Setting.key == "ai_config").first()
    if not raw or not raw.value:
        return {"status": "error", "message": "未配置 AI 参数"}
    
    config = json.loads(raw.value)
    api_base = config.get("api_base", "")
    api_key = config.get("api_key", "")
    model_name = config.get("model_name", "")
    
    if not api_base or not api_key:
        return {"status": "error", "message": "API Base URL 和 API Key 不能为空"}
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{api_base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model_name or "qwen-plus", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}
            )
            if resp.status_code == 200:
                return {"status": "ok", "message": f"连接成功，模型 {model_name or '默认'} 可用"}
            else:
                return {"status": "error", "message": f"API 返回 {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"status": "error", "message": f"连接失败: {str(e)[:200]}"}


# ===== OpenClaw 绑定 =====

OPENCLAW_GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://localhost:18789")

@router.get("/settings/openclaw-agents")
async def list_openclaw_agents(user: User = Depends(require_user)):
    """从 OpenClaw Gateway 获取可用 agent 清单"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OPENCLAW_GATEWAY_URL}/api/agents")
            if resp.status_code == 200:
                data = resp.json()
                agents = data.get("agents", [])
                return {
                    "status": "ok",
                    "gateway_url": OPENCLAW_GATEWAY_URL,
                    "agents": [{"id": a.get("id", a.get("agentId", "")), "label": a.get("label", a.get("id", ""))} for a in agents]
                }
            else:
                return {"status": "error", "message": f"Gateway 返回 {resp.status_code}", "agents": []}
    except httpx.ConnectError:
        return {"status": "error", "message": "无法连接 OpenClaw Gateway，请确认地址和端口", "agents": []}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200], "agents": []}


class OpenClawBindRequest(BaseModel):
    agent_id: str  # OpenClaw agent id
    agent_label: Optional[str] = None  # 显示名


@router.get("/settings/openclaw-binding")
@router.get("/settings/openclaw-bindding")  # 兼容旧拼写
async def get_openclaw_binding(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取当前 OpenClaw 绑定关系"""
    raw = db.query(Setting).filter(Setting.key == "openclaw_binding").first()
    if raw and raw.value:
        import json
        return json.loads(raw.value)
    return {"bound": False, "agent_id": "", "agent_label": ""}


@router.post("/settings/openclaw-binding")
@router.post("/settings/openclaw-bindding")  # 兼容旧拼写
async def set_openclaw_binding(req: OpenClawBindRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """设置 OpenClaw 绑定关系"""
    import json
    binding = {"bound": True, "agent_id": req.agent_id, "agent_label": req.agent_label or req.agent_id, "bound_at": datetime.utcnow().isoformat()}
    raw = db.query(Setting).filter(Setting.key == "openclaw_binding").first()
    if raw:
        raw.value = json.dumps(binding)
    else:
        db.add(Setting(key="openclaw_binding", value=json.dumps(binding)))
    db.commit()
    return binding


@router.delete("/settings/openclaw-binding")
@router.delete("/settings/openclaw-bindding")  # 兼容旧拼写
async def delete_openclaw_binding(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """解除 OpenClaw 绑定"""
    import json
    raw = db.query(Setting).filter(Setting.key == "openclaw_binding").first()
    if raw:
        raw.value = json.dumps({"bound": False, "agent_id": "", "agent_label": ""})
        db.commit()
    return {"bound": False}


# ===== 调度器状态 =====
