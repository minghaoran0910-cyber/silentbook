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

@router.post("/parse")
async def parse_notification(notification: dict, user: User = Depends(require_user)):
    """解析通知并创建交易"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{PARSER_API_URL}/parse",
                json=notification,
                timeout=10.0
            )
            response.raise_for_status()
            parsed = response.json()

            # V2-038: 检查是否被过滤器过滤（非财务通知）
            if parsed.get("filtered"):
                return {
                    "message": "Notification filtered as non-financial",
                    "filtered": True,
                    "reason": parsed.get("filter_reason", ""),
                }

            # 验证必要字段
            required_fields = ["amount", "category", "account", "transaction_type"]
            for field in required_fields:
                if field not in parsed:
                    raise HTTPException(status_code=500, detail=f"解析结果缺少字段: {field}")

            # 创建交易记录
            db = SessionLocal()
            try:
                db_transaction = Transaction(
                    amount=parsed["amount"],
                    category=parsed["category"],
                    account=parsed["account"],
                    description=parsed.get("description", ""),
                    transaction_type=parsed["transaction_type"],
                    raw_text=parsed.get("raw_text", ""),
                    confidence=parsed.get("confidence", 0.5),
                    parsed_at=datetime.utcnow()
                )
                db.add(db_transaction)
                db.flush()
                # 联动账户余额
                new_balance = _update_account_balance(db, parsed["account"], parsed["transaction_type"], parsed["amount"])
                db.commit()
                db.refresh(db_transaction)
                # IMP-040: 低余额主动告警
                if new_balance is not None and new_balance < 100.0 and parsed["transaction_type"] == "expense":
                    logger.warning(f"IMP-040 低余额告警: {parsed['account']} 余额¥{new_balance:.2f}")
                return {
                    "status": "created",
                    "message": "Transaction created",
                    "id": db_transaction.id,
                    "amount": db_transaction.amount,
                    "category": db_transaction.category,
                    "type": db_transaction.transaction_type,
                }
            finally:
                db.close()

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"通知解析器返回错误: {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"无法连接通知解析器: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")


# ===== Webhook 接入 =====


class WebhookRequest(BaseModel):
    title: str = ""
    body: str
    source: str = "webhook"
    timestamp: Optional[str] = None


async def _background_push_and_analyze(tx_id: int, tx_data: dict, user_id: int):
    """后台执行推送和分析，不阻塞 webhook 响应"""
    from ..database import SessionLocal
    db = SessionLocal()
    tenant_token = set_tenant_user_id(user_id)
    try:
        tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
        if not tx:
            return
        # 推送通知
        try:
            await pusher.push_transaction(tx_data)
        except Exception as e:
            logger.warning(f"后台推送失败: {e}")
        # 异常检测 + 分析
        try:
            await check_abnormal_and_analyze(tx, db)
        except Exception as e:
            logger.warning(f"后台分析失败: {e}")
    finally:
        db.close()
        reset_tenant_user_id(tenant_token)


async def verify_webhook(
    request: Request,
    x_silentbook_timestamp: str = Header(...),
    x_silentbook_event_id: str = Header(...),
    x_silentbook_signature: str = Header(...),
    db: Session = Depends(get_db),
) -> int:
    """Verify HMAC, reject stale/replayed events, and select the webhook owner."""
    secret = os.getenv("WEBHOOK_SECRET", "")
    configured_user_id = os.getenv("WEBHOOK_USER_ID", "")
    if not secret or len(secret) < 32 or not configured_user_id.isdigit():
        logger.error("Webhook security configuration is missing or unsafe")
        raise HTTPException(status_code=503, detail="Webhook is not configured")
    try:
        timestamp = int(x_silentbook_timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid webhook timestamp")
    if abs(int(time.time()) - timestamp) > 300:
        raise HTTPException(status_code=401, detail="Webhook timestamp expired")
    if not x_silentbook_event_id or len(x_silentbook_event_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid webhook event id")

    body = await request.body()
    max_body_bytes = int(os.getenv("WEBHOOK_MAX_BODY_BYTES", "1048576"))
    if len(body) > max_body_bytes:
        raise HTTPException(status_code=413, detail="Webhook body is too large")
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    supplied = x_silentbook_signature.removeprefix("sha256=")
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    user_id = int(configured_user_id)
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=503, detail="Webhook owner is unavailable")
    set_tenant_user_id(user_id)
    if db.query(WebhookEvent).filter(WebhookEvent.event_id == x_silentbook_event_id).first():
        raise HTTPException(status_code=409, detail="Duplicate webhook event")
    db.add(WebhookEvent(event_id=x_silentbook_event_id, signature_timestamp=timestamp))
    try:
        # Reserve the event inside the request transaction. The route's transaction
        # commit persists it together with the resulting ledger changes; failures
        # roll both back so a legitimate sender can retry.
        db.flush()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate webhook event")
    return user_id


@router.post("/webhook/notify")
async def webhook_notify(req: WebhookRequest, background_tasks: BackgroundTasks, user_id: int = Depends(verify_webhook), db: Session = Depends(get_db)):
    """接收通知 webhook，自动解析并存入交易记录。推送和分析在后台异步执行。"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{PARSER_API_URL}/parse",
                json={"title": req.title, "body": req.body, "source": req.source, "timestamp": req.timestamp},
                timeout=10.0
            )
            response.raise_for_status()
            parsed = response.json()
            
            # V2-038: 检查是否被过滤器过滤（非财务通知）
            if parsed.get("filtered"):
                return {
                    "status": "filtered",
                    "reason": parsed.get("filter_reason", ""),
                    "message": "非财务通知，已过滤",
                }
            
            required = ["amount", "category", "account", "transaction_type"]
            for field in required:
                if field not in parsed:
                    raise HTTPException(status_code=422, detail=f"解析结果缺少字段: {field}")

            # 业务级幂等：同一条通知换 event_id 重试也不重记
            body_hash = _webhook_item_hash(req.title, req.body, req.source, req.timestamp)
            if _is_duplicate_body(db, body_hash):
                return {"status": "duplicate", "message": "重复通知，已去重"}

            db_tx = Transaction(
                amount=parsed["amount"],
                category=parsed["category"],
                account=parsed["account"],
                description=parsed.get("description", ""),
                transaction_type=parsed["transaction_type"],
                raw_text=parsed.get("raw_text", ""),
                confidence=parsed.get("confidence", 0.5),
                parsed_at=datetime.utcnow()
            )
            db.add(db_tx)
            db.flush()
            # 联动账户余额
            new_balance = _update_account_balance(db, parsed["account"], parsed["transaction_type"], parsed["amount"])
            # 业务去重行与账本同事务提交；并发竞态由唯一索引兜底判重
            db.add(WebhookEvent(
                event_id=f"body:{body_hash}",
                body_hash=body_hash,
                signature_timestamp=int(time.time()),
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                logger.warning("webhook body_hash 冲突，并发重试判重")
                return {"status": "duplicate", "message": "重复通知，已去重"}
            db.refresh(db_tx)
            
            # IMP-040: 低余额主动告警
            background_tasks.add_task(
                _check_low_balance_alert,
                parsed["account"], new_balance, parsed["amount"], parsed["transaction_type"]
            )
            
            # 后台异步执行推送和分析
            tx_data = {
                "amount": db_tx.amount,
                "category": db_tx.category,
                "account": db_tx.account,
                "transaction_type": db_tx.transaction_type,
                "description": db_tx.description,
                "parsed_at": db_tx.parsed_at
            }
            background_tasks.add_task(_background_push_and_analyze, db_tx.id, tx_data, user_id)
            
            return {
                "status": "created",
                "id": db_tx.id,
                "amount": db_tx.amount,
                "category": db_tx.category,
                "type": db_tx.transaction_type,
                "confidence": db_tx.confidence,
                "message": "记账成功，分析和推送在后台执行"
            }
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"通知解析器返回错误: {e.response.status_code}")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="通知解析器不可用")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"入账失败: {str(e)}")


@router.post("/webhook/notify/batch")
async def webhook_notify_batch(
    items: List[WebhookRequest],
    background_tasks: BackgroundTasks,
    user_id: int = Depends(verify_webhook),
    db: Session = Depends(get_db)
):
    """批量接收通知"""
    results = []
    if len(items) > 100:
        raise HTTPException(status_code=413, detail="Batch webhook accepts at most 100 items")
    for item in items:
        try:
            result = await webhook_notify(item, background_tasks, user_id, db)
        except HTTPException as e:
            # 单条失败不炸整批，转为条目级错误（调用方按 results 逐条处理）
            result = {"status": "error", "reason": e.detail}
        results.append(result)
    return {"total": len(items), "results": results}


# ===== 事件驱动分析 =====

# 异常消费阈值（可配置）


ABNORMAL_THRESHOLD = float(os.getenv("ABNORMAL_THRESHOLD", "500"))
ABNORMAL_CATEGORIES = ["娱乐", "游戏", "彩票", "赌博"]

async def check_abnormal_and_analyze(tx: Transaction, db: Session) -> dict:
    """检测异常交易并自动触发分析"""
    is_abnormal = False
    reasons = []
    
    # 规则1: 金额超阈值
    if tx.transaction_type == "expense" and tx.amount and tx.amount >= ABNORMAL_THRESHOLD:
        is_abnormal = True
        reasons.append(f"大额消费 ¥{tx.amount}")
    
    # 规则2: 异常分类
    if tx.category in ABNORMAL_CATEGORIES:
        is_abnormal = True
        reasons.append(f"异常分类: {tx.category}")
    
    # 规则3: 同日同类重复消费 >=3 次
    if tx.parsed_at:
        today_start = tx.parsed_at.replace(hour=0, minute=0, second=0, microsecond=0)
        same_day_same_cat = db.query(Transaction).filter(
            Transaction.category == tx.category,
            Transaction.parsed_at >= today_start,
            Transaction.parsed_at <= tx.parsed_at
        ).count()
        if same_day_same_cat >= 3:
            is_abnormal = True
            reasons.append(f"同日同类消费 {same_day_same_cat} 次")
    
    if not is_abnormal:
        return {"triggered": False}
    
    # 触发分析
    try:
        recent_txs = db.query(Transaction).order_by(
            Transaction.parsed_at.desc()
        ).limit(50).all()
        
        tx_data = [{
            "amount": t.amount, "category": t.category,
            "transaction_type": t.transaction_type,
            "description": t.description, "parsed_at": str(t.parsed_at or "")
        } for t in recent_txs]
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{AGENT_API_URL}/analyze",
                json={"transactions": tx_data},
                timeout=120.0
            )
            if resp.status_code == 200:
                result = resp.json()
                # 占位警告不入库
                if _is_placeholder_analysis(result):
                    logger.warning("事件驱动分析返回占位警告，本次不入库")
                    return {"triggered": True, "reasons": reasons, "analysis_saved": False}
                # 保存分析结果
                for analysis_type in ["consumption", "investment", "suggestion"]:
                    analysis = AnalysisResult(
                        agent_name="event-driven",
                        analysis_type=analysis_type,
                        content=result.get(analysis_type, "")
                    )
                    db.add(analysis)
                db.commit()
                return {
                    "triggered": True,
                    "reasons": reasons,
                    "analysis_saved": True
                }
    except Exception as e:
        logger.error(f"事件驱动分析失败: {e}")
        return {"triggered": True, "reasons": reasons, "analysis_saved": False, "error": str(e)}


# ===== 统计 =====


@router.get("/analysis/results")
async def get_analysis_results(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """分析结果（兼容旧路径，等同于 /analysis/latest）"""
    return await get_latest_analysis(user=user, db=db)


@router.get("/agent/configs")
async def get_agent_configs_alias(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Agent 配置（兼容旧路径，等同于 /settings/agents）"""
    agents = db.query(AgentConfig).all()
    return [{
        "id": a.id, "name": a.name, "api_endpoint": a.api_endpoint,
        "is_active": a.is_active, "system_prompt": a.system_prompt or ""
    } for a in agents]
