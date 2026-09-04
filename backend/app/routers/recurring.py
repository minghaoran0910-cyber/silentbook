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

def _recurring_to_response(rt: RecurringTransaction) -> RecurringTransactionResponse:
    """Convert RecurringTransaction ORM object to response schema."""
    return RecurringTransactionResponse(
        id=rt.id,
        name=rt.name,
        amount=rt.amount,
        category=rt.category,
        transaction_type=rt.transaction_type,
        frequency=rt.frequency,
        day_of_month=rt.day_of_month,
        day_of_week=rt.day_of_week,
        start_date=rt.start_date.isoformat() if rt.start_date else None,
        end_date=rt.end_date.isoformat() if rt.end_date else None,
        account=rt.account,
        is_active=rt.is_active,
        source=rt.source,
        confidence=rt.confidence,
        notes=rt.notes,
        created_at=rt.created_at,
        updated_at=rt.updated_at,
    )


def _monthly_amount(rt: RecurringTransaction) -> float:
    """Convert any frequency to approximate monthly amount."""
    freq_map = {
        "daily": 30,
        "weekly": 4.33,
        "biweekly": 2.17,
        "monthly": 1,
        "quarterly": 1/3,
        "yearly": 1/12,
    }
    multiplier = freq_map.get(rt.frequency, 1)
    return rt.amount * multiplier


@router.get("/recurring", response_model=List[RecurringTransactionResponse])
async def list_recurring_transactions(
    is_active: Optional[bool] = None,
    transaction_type: Optional[str] = None,
    frequency: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """获取固定收支列表，支持按状态/类型/频率筛选"""
    query = db.query(RecurringTransaction)

    if is_active is not None:
        query = query.filter(RecurringTransaction.is_active == is_active)
    if transaction_type:
        query = query.filter(RecurringTransaction.transaction_type == transaction_type)
    if frequency:
        query = query.filter(RecurringTransaction.frequency == frequency)

    items = query.order_by(RecurringTransaction.day_of_month.asc()).all()
    return [_recurring_to_response(rt) for rt in items]


@router.post("/recurring", response_model=RecurringTransactionResponse, status_code=201)
async def create_recurring_transaction(
    data: RecurringTransactionCreate,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """创建固定收支"""
    # 日期解析验证
    start_date = None
    end_date = None
    if data.start_date:
        try:
            start_date = date.fromisoformat(data.start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_date 格式错误，应为 YYYY-MM-DD")
    if data.end_date:
        try:
            end_date = date.fromisoformat(data.end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_date 格式错误，应为 YYYY-MM-DD")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date 不能早于 start_date")

    rt = RecurringTransaction(
        name=data.name,
        amount=data.amount,
        category=data.category,
        transaction_type=data.transaction_type,
        frequency=data.frequency,
        day_of_month=data.day_of_month,
        day_of_week=data.day_of_week,
        start_date=start_date,
        end_date=end_date,
        account=data.account,
        is_active=data.is_active,
        source="manual",
        confidence=1.0,
        notes=data.notes,
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)
    return _recurring_to_response(rt)


@router.get("/recurring/summary", response_model=RecurringSummaryResponse)
async def get_recurring_summary(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """固定收支月度汇总：所有启用项折算为月度金额"""
    items = db.query(RecurringTransaction).filter(
        RecurringTransaction.is_active == True
    ).order_by(RecurringTransaction.day_of_month.asc()).all()

    total_income = 0.0
    total_expense = 0.0
    income_count = 0
    expense_count = 0

    for rt in items:
        monthly = _monthly_amount(rt)
        if rt.transaction_type == "income":
            total_income += monthly
            income_count += 1
        else:
            total_expense += monthly
            expense_count += 1

    return RecurringSummaryResponse(
        total_monthly_income=round(total_income, 2),
        total_monthly_expense=round(total_expense, 2),
        monthly_net=round(total_income - total_expense, 2),
        income_count=income_count,
        expense_count=expense_count,
        active_count=len(items),
        items=[_recurring_to_response(rt) for rt in items],
    )


@router.post("/recurring/auto-detect", response_model=AutoDetectResponse)
async def auto_detect_recurring(
    history_days: int = 90,
    import_detected: bool = False,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """从历史交易自动检测固定收支
    
    算法：同分类 + 相似金额(5%容差) + 跨月出现 >= 2次
    import_detected=True 时自动导入为 source=auto 的记录
    """
    now = datetime.utcnow()
    history_start = now - timedelta(days=history_days)

    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= history_start
    ).all()

    if not transactions:
        return AutoDetectResponse(detected_count=0, imported_count=0, skipped_count=0, items=[])

    # 按分类分组
    by_category = {}
    for tx in transactions:
        cat = tx.category or "其他"
        by_category.setdefault(cat, []).append(tx)

    detected = []
    for cat, cat_txs in by_category.items():
        # 按相似金额聚类
        amount_clusters = []
        for tx in cat_txs:
            matched = False
            for cluster in amount_clusters:
                if cluster and abs(tx.amount - cluster[0].amount) / max(cluster[0].amount, 0.01) < 0.05:
                    cluster.append(tx)
                    matched = True
                    break
            if not matched:
                amount_clusters.append([tx])

        for cluster in amount_clusters:
            if len(cluster) < 2:
                continue

            # 检查跨月
            months = set()
            for tx in cluster:
                if tx.parsed_at:
                    months.add((tx.parsed_at.year, tx.parsed_at.month))

            if len(months) < 2:
                continue

            doms = [tx.parsed_at.day for tx in cluster if tx.parsed_at]
            avg_dom = sum(doms) / len(doms)
            max_dev = max(abs(d - avg_dom) for d in doms)

            # 日方差 > 3 天 → 不是月度固定
            if max_dev > 3:
                continue

            avg_amount = sum(tx.amount for tx in cluster) / len(cluster)
            avg_dom_int = min(round(avg_dom), 28)

            # 计算置信度：出现次数越多、跨月越多 → 置信度越高
            confidence = min(0.5 + len(months) * 0.15 + len(cluster) * 0.05, 1.0)

            detected.append({
                "category": cat,
                "amount": round(avg_amount, 2),
                "day_of_month": avg_dom_int,
                "transaction_type": cluster[0].transaction_type,
                "occurrence_count": len(cluster),
                "months_spanned": len(months),
                "confidence": round(confidence, 2),
                "name": f"{cat}（自动检测）",
            })

    # 去重：与已有 auto 记录对比
    existing_auto = db.query(RecurringTransaction).filter(
        RecurringTransaction.source == "auto",
        RecurringTransaction.is_active == True
    ).all()
    existing_keys = {(rt.category, rt.transaction_type, rt.day_of_month) for rt in existing_auto}

    imported_count = 0
    skipped_count = 0

    if import_detected:
        for item in detected:
            key = (item["category"], item["transaction_type"], item["day_of_month"])
            if key in existing_keys:
                skipped_count += 1
                continue

            rt = RecurringTransaction(
                name=item["name"],
                amount=item["amount"],
                category=item["category"],
                transaction_type=item["transaction_type"],
                frequency="monthly",
                day_of_month=item["day_of_month"],
                source="auto",
                confidence=item["confidence"],
                is_active=True,
            )
            db.add(rt)
            imported_count += 1

        db.commit()

    return AutoDetectResponse(
        detected_count=len(detected),
        imported_count=imported_count,
        skipped_count=skipped_count,
        items=detected,
    )


@router.get("/recurring/{recurring_id}", response_model=RecurringTransactionResponse)
async def get_recurring_transaction(recurring_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取单个固定收支详情"""
    rt = db.query(RecurringTransaction).filter(RecurringTransaction.id == recurring_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="固定收支记录不存在")
    return _recurring_to_response(rt)


@router.put("/recurring/{recurring_id}", response_model=RecurringTransactionResponse)
async def update_recurring_transaction(
    recurring_id: int,
    data: RecurringTransactionUpdate,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """更新固定收支"""
    rt = db.query(RecurringTransaction).filter(RecurringTransaction.id == recurring_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="固定收支记录不存在")

    update_data = data.model_dump(exclude_unset=True)

    # 日期字段特殊处理
    if "start_date" in update_data:
        if update_data["start_date"]:
            try:
                update_data["start_date"] = date.fromisoformat(update_data["start_date"])
            except ValueError:
                raise HTTPException(status_code=400, detail="start_date 格式错误")
        else:
            update_data["start_date"] = None

    if "end_date" in update_data:
        if update_data["end_date"]:
            try:
                update_data["end_date"] = date.fromisoformat(update_data["end_date"])
            except ValueError:
                raise HTTPException(status_code=400, detail="end_date 格式错误")
        else:
            update_data["end_date"] = None

    # start_date + end_date 交叉验证
    new_start = update_data.get("start_date", rt.start_date)
    new_end = update_data.get("end_date", rt.end_date)
    if new_start and new_end and new_end < new_start:
        raise HTTPException(status_code=400, detail="end_date 不能早于 start_date")

    for key, value in update_data.items():
        setattr(rt, key, value)

    rt.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rt)
    return _recurring_to_response(rt)


@router.delete("/recurring/{recurring_id}")
async def delete_recurring_transaction(recurring_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """删除固定收支"""
    rt = db.query(RecurringTransaction).filter(RecurringTransaction.id == recurring_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="固定收支记录不存在")

    db.delete(rt)
    db.commit()
    return {"message": "已删除", "id": recurring_id}


# ===== 日志管理 API =====
