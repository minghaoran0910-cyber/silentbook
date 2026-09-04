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

@router.get("/accounts", response_model=List[AccountResponse])
async def list_accounts(
    purpose: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """获取账户列表"""
    query = db.query(Account)
    if purpose:
        query = query.filter(Account.purpose == purpose)
    if status:
        query = query.filter(Account.status == status)
    return query.order_by(Account.updated_at.desc()).all()


@router.post("/accounts", response_model=AccountResponse)
async def create_account(account: AccountCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """创建账户"""
    db_account = Account(**account.model_dump())
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account


@router.get("/accounts/summary")
async def get_accounts_summary(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """四账户体系汇总：按 purpose 分组统计"""
    accounts = db.query(Account).filter(Account.status == "active").all()
    
    purpose_labels = {
        "consumption": "日常消费",
        "emergency": "应急储备",
        "investment": "投资增值",
        "goal": "目标储蓄",
    }
    
    summary = {}
    total_balance = 0
    for purpose, label in purpose_labels.items():
        purpose_accounts = [a for a in accounts if a.purpose == purpose]
        balance_sum = sum(a.balance for a in purpose_accounts)
        target_sum = sum(a.target_balance for a in purpose_accounts)
        summary[purpose] = {
            "label": label,
            "account_count": len(purpose_accounts),
            "total_balance": round(balance_sum, 2),
            "total_target": round(target_sum, 2),
            "achievement_rate": round(balance_sum / target_sum * 100, 1) if target_sum > 0 else 0,
            "accounts": [
                {"id": a.id, "name": a.name, "balance": a.balance, "target_balance": a.target_balance}
                for a in purpose_accounts
            ]
        }
        total_balance += balance_sum
    
    return {
        "total_balance": round(total_balance, 2),
        "purposes": summary
    }


@router.get("/accounts/transfers", response_model=List[TransferResponse])
async def list_transfers(
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = Query(default=50, le=200),
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """获取转账历史列表"""
    query = db.query(Transfer)
    if account_id:
        query = query.filter(
            (Transfer.from_account_id == account_id) | (Transfer.to_account_id == account_id)
        )
    return query.order_by(Transfer.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/accounts/transfers/{transfer_id}", response_model=TransferResponse)
async def get_transfer(transfer_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取单条转账记录"""
    transfer = db.query(Transfer).filter(Transfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="转账记录不存在")
    return transfer


@router.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(account_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取单个账户"""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")
    return account


@router.put("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    account_update: AccountUpdate,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """更新账户"""
    db_account = db.query(Account).filter(Account.id == account_id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="账户不存在")
    
    update_data = account_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_account, key, value)
    db_account.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_account)
    return db_account


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """删除账户"""
    db_account = db.query(Account).filter(Account.id == account_id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="账户不存在")
    db.delete(db_account)
    db.commit()
    return {"message": "已删除"}


@router.post("/accounts/transfer")
async def transfer_between_accounts(transfer: AccountTransfer, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """账户间转账：扣减余额 + 增加余额 + 记录转账历史"""
    from_acc = db.query(Account).filter(Account.id == transfer.from_account_id).first()
    to_acc = db.query(Account).filter(Account.id == transfer.to_account_id).first()
    
    if not from_acc:
        raise HTTPException(status_code=404, detail="转出账户不存在")
    if not to_acc:
        raise HTTPException(status_code=404, detail="转入账户不存在")
    if from_acc.balance < transfer.amount:
        raise HTTPException(status_code=400, detail=f"余额不足：当前余额 {from_acc.balance}")
    
    from_acc.balance -= transfer.amount
    to_acc.balance += transfer.amount
    from_acc.updated_at = datetime.utcnow()
    to_acc.updated_at = datetime.utcnow()
    
    # 保存转账记录
    transfer_record = Transfer(
        from_account_id=transfer.from_account_id,
        to_account_id=transfer.to_account_id,
        amount=transfer.amount,
        description=transfer.description,
    )
    db.add(transfer_record)
    
    # 记录转账交易
    tx_out = Transaction(
        amount=transfer.amount,
        category="转账",
        account=from_acc.name,
        description=f"转出至 {to_acc.name}" + (f": {transfer.description}" if transfer.description else ""),
        transaction_type="expense",
        confidence=1.0,
        parsed_at=datetime.utcnow()
    )
    tx_in = Transaction(
        amount=transfer.amount,
        category="转账",
        account=to_acc.name,
        description=f"从 {from_acc.name} 转入" + (f": {transfer.description}" if transfer.description else ""),
        transaction_type="income",
        confidence=1.0,
        parsed_at=datetime.utcnow()
    )
    db.add(tx_out)
    db.add(tx_in)
    db.commit()
    db.refresh(transfer_record)
    
    return {
        "status": "ok",
        "transfer_id": transfer_record.id,
        "from_account": {"id": from_acc.id, "name": from_acc.name, "balance": from_acc.balance},
        "to_account": {"id": to_acc.id, "name": to_acc.name, "balance": to_acc.balance},
        "amount": transfer.amount
    }

# ===== 资产管理 =====
