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
    get_alert_level, get_category_level, normalize_account_name,
)

router = APIRouter()

logger = logging.getLogger("silentbook")

@router.post("/transactions", response_model=TransactionResponse)
async def create_transaction(transaction: TransactionCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """创建交易记录（手动或自动），同时联动账户余额"""
    db_transaction = Transaction(
        amount=transaction.amount,
        category=transaction.category,
        account=normalize_account_name(transaction.account),
        description=transaction.description,
        transaction_type=transaction.transaction_type,
        raw_text=transaction.raw_text,
        confidence=transaction.confidence,
        parsed_at=datetime.utcnow()
    )
    db.add(db_transaction)
    db.flush()  # 获取 ID 但不提交
    
    # 联动账户余额
    _update_account_balance(db, transaction.account, transaction.transaction_type, transaction.amount)
    
    db.commit()
    db.refresh(db_transaction)
    return db_transaction


@router.get("/transactions", response_model=List[TransactionResponse])
async def list_transactions(
    skip: int = 0,
    limit: int = Query(default=100, le=1000),
    account: Optional[str] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    hide_noise: bool = Query(False, description="隐藏0元非财务通知"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    """获取交易列表"""
    query = db.query(Transaction)
    if account:
        # 兼容平台标识与中文名两种写法（cmb 与 招商银行查到同一批）
        query = query.filter(Transaction.account.in_(
            [account, normalize_account_name(account)]))
    if category:
        query = query.filter(Transaction.category == category)
    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)
    if hide_noise:
        query = query.filter(Transaction.amount > 0)
    return query.order_by(Transaction.parsed_at.desc()).offset(skip).limit(limit).all()


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(transaction_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取单个交易"""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction


@router.put("/transactions/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: int,
    transaction: TransactionUpdate,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """更新交易记录，同时联动账户余额"""
    db_transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if db_transaction.category == "转账":
        raise HTTPException(status_code=400, detail="转账流水由转账记录联动余额，不支持直接修改（避免重复计算）")

    # 先回滚旧交易的余额影响
    _update_account_balance(db, db_transaction.account, db_transaction.transaction_type, db_transaction.amount, reverse=True)

    update_data = transaction.model_dump(exclude_unset=True)
    if "account" in update_data:
        update_data["account"] = normalize_account_name(update_data["account"])
    for field, value in update_data.items():
        setattr(db_transaction, field, value)

    # 应用新交易的余额影响
    _update_account_balance(db, db_transaction.account, db_transaction.transaction_type, db_transaction.amount)

    db.commit()
    db.refresh(db_transaction)
    return db_transaction


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(transaction_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """删除交易，同时回滚账户余额"""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.category == "转账":
        raise HTTPException(status_code=400, detail="转账流水由转账记录联动余额，不支持直接删除（避免余额错乱）")
    # 回滚余额
    _update_account_balance(db, transaction.account, transaction.transaction_type, transaction.amount, reverse=True)
    db.delete(transaction)
    db.commit()
    return {"message": "Transaction deleted"}


@router.delete("/transactions")
async def delete_all_transactions(confirm: bool = Query(False), user: User = Depends(require_user), db: Session = Depends(get_db)):
    """清空所有交易（需要确认）"""
    if not confirm:
        raise HTTPException(status_code=400, detail="需要确认参数 confirm=true")
    # 逐笔回滚余额影响后再删，避免账户余额与流水脱钩（保留开户初始余额）
    transactions = db.query(Transaction).all()
    for t in transactions:
        _update_account_balance(db, t.account, t.transaction_type, t.amount, reverse=True)
    count = len(transactions)
    db.query(Transaction).delete()
    db.commit()
    return {"message": f"Deleted {count} transactions（账户余额已同步回滚）"}
