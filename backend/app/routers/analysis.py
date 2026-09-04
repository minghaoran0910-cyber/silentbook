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
from .ingest import verify_webhook
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

@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """调用 Agent 进行分析"""
    # 获取交易数据
    transactions = db.query(Transaction).order_by(Transaction.parsed_at.desc()).limit(100).all()
    # 获取资产和负债数据
    assets = db.query(Asset).filter(Asset.status == "active").all()
    liabilities = db.query(Liability).filter(Liability.status == "active").all()

    # 调用 Agent API
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{AGENT_API_URL}/analyze",
                json={
                    "transactions": [
                        {
                            "amount": t.amount,
                            "category": t.category,
                            "account": t.account,
                            "description": t.description,
                            "transaction_type": t.transaction_type,
                            "parsed_at": t.parsed_at.isoformat()
                        }
                        for t in transactions
                    ],
                    "assets": [
                        {
                            "name": a.name,
                            "asset_type": a.asset_type,
                            "current_value": a.current_value,
                            "initial_value": a.initial_value,
                        }
                        for a in assets
                    ],
                    "liabilities": [
                        {
                            "name": l.name,
                            "liability_type": l.liability_type,
                            "current_amount": l.current_amount,
                            "total_amount": l.total_amount,
                        }
                        for l in liabilities
                    ]
                },
                timeout=120.0
            )
            result = response.json()
        except Exception as e:
            result = {
                "consumption": "Agent 服务暂不可用",
                "investment": "Agent 服务暂不可用",
                "suggestion": "请检查 Agent 服务状态"
            }

    # 保存分析结果（占位警告不入库，避免污染历史）
    if _is_placeholder_analysis(result):
        logger.warning("AI 未配置或 Agent 不可用，本次分析不入库")
        return result
    agent_name = result.get("mode", "default")
    for analysis_type in ["consumption", "investment", "suggestion"]:
        analysis = AnalysisResult(
            agent_name=agent_name,
            analysis_type=analysis_type,
            content=result.get(analysis_type, "")
        )
        db.add(analysis)
    db.commit()

    return result


@router.get("/analysis/latest", response_model=AnalysisResponse)
async def get_latest_analysis(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取最新分析结果"""
    latest = db.query(AnalysisResult).order_by(AnalysisResult.created_at.desc()).first()
    if not latest:
        return AnalysisResponse(
            consumption="暂无分析",
            investment="暂无分析",
            suggestion="点击分析按钮获取 AI 建议"
        )

    # 同一批次的记录创建时间相差在几秒内（微秒精度导致不完全一致）
    # 用 10 秒窗口匹配同一批次的所有类型
    from datetime import timedelta
    batch_time = latest.created_at
    analyses = db.query(AnalysisResult).filter(
        AnalysisResult.created_at >= batch_time - timedelta(seconds=5),
        AnalysisResult.created_at <= batch_time + timedelta(seconds=5)
    ).all()

    result = {}
    for a in analyses:
        result[a.analysis_type] = a.content

    return AnalysisResponse(
        consumption=result.get("consumption", "暂无分析"),
        investment=result.get("investment", "暂无分析"),
        suggestion=result.get("suggestion", "暂无建议"),
        mode=result.get("mode", "")
    )


@router.get("/analysis/history")
async def get_analysis_history(limit: int = 20, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取历史分析列表"""
    records = db.query(AnalysisResult).order_by(
        AnalysisResult.created_at.desc()
    ).limit(limit * 3).all()
    
    # 按 created_at 分组
    batches = {}
    for r in records:
        batch_time = r.created_at.isoformat() if r.created_at else "unknown"
        if batch_time not in batches:
            batches[batch_time] = {
                "created_at": batch_time,
                "items": []
            }
        batches[batch_time]["items"].append({
            "id": r.id,
            "analysis_type": r.analysis_type,
            "content": r.content,
            "agent_name": r.agent_name
        })
    
    return list(batches.values())[:limit]


class AnalysisImport(BaseModel):
    consumption: str = Field(..., min_length=1)
    investment: str = Field(..., min_length=1)
    suggestion: str = Field(..., min_length=1)
    agent_name: str = Field(default="openclaw-webhook", max_length=100)


@router.post("/analysis/import")
async def import_analysis(
    payload: AnalysisImport,
    user_id: int = Depends(verify_webhook),
    db: Session = Depends(get_db),
):
    """OpenClaw automation 投递分析结果（HMAC 签名，同 webhook 规范）。

    正确用法（OpenClaw 侧）：
    openclaw automations create "0 20 * * *" "<prompt，要求只输出 consumption/investment/suggestion 三段>"
      --agent <你的agent> --webhook https://<host>/api/analysis/import
    注意 automation 的 webhook 投递是 OpenClaw 信封格式，需要一层小脚本把
    三段抽出来按本接口签名重推（见 docs/openclaw-integration.md）。
    占位警告不入库；同体重试返回 duplicate。
    """
    body_hash = _webhook_item_hash(
        payload.agent_name, payload.consumption + payload.investment,
        payload.suggestion, "",
    )
    if _is_duplicate_body(db, body_hash):
        return {"status": "duplicate", "message": "重复投递，已去重"}
    result = {
        "consumption": payload.consumption,
        "investment": payload.investment,
        "suggestion": payload.suggestion,
    }
    if _is_placeholder_analysis(result):
        return {"status": "skipped", "message": "占位内容不入库"}
    for analysis_type in ("consumption", "investment", "suggestion"):
        db.add(AnalysisResult(
            agent_name=payload.agent_name,
            analysis_type=analysis_type,
            content=result[analysis_type],
        ))
    try:
        db.add(WebhookEvent(
            event_id=f"body:{body_hash}",
            body_hash=body_hash,
            signature_timestamp=int(time.time()),
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate", "message": "重复投递，已去重"}
    return {"status": "created", "message": "分析已入库"}


# ===== PDF 导入 =====

from fastapi import UploadFile, File
