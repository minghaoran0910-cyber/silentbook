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

@router.get("/stats/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取仪表盘统计数据"""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 本月收入（使用聚合查询）
    monthly_income = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.transaction_type == "income",
        Transaction.parsed_at >= month_start
    ).scalar() or 0.0

    # 本月支出
    monthly_expenses = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.transaction_type == "expense",
        Transaction.parsed_at >= month_start
    ).scalar() or 0.0

    # 总资产（使用聚合查询）
    total_income = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.transaction_type == "income"
    ).scalar() or 0.0
    
    total_expenses = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.transaction_type == "expense"
    ).scalar() or 0.0
    
    # 资产总值
    total_assets = db.query(func.coalesce(func.sum(Asset.current_value), 0)).filter(
        Asset.status == "active"
    ).scalar() or 0.0

    # 负债总值
    total_liabilities = db.query(func.coalesce(func.sum(Liability.current_amount), 0)).filter(
        Liability.status == "active"
    ).scalar() or 0.0

    # 净资产 = 总资产 - 总负债（交易已体现在资产值中，不应重复计算）
    net_assets = total_assets - total_liabilities

    # 交易笔数
    transaction_count = db.query(Transaction).count()

    return DashboardStats(
        net_assets=net_assets,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        monthly_income=monthly_income,
        monthly_expenses=monthly_expenses,
        transaction_count=transaction_count
    )


@router.get("/stats/trend")
async def get_trend(days: int = 30, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取最近 N 天的消费趋势"""
    start_date = datetime.utcnow() - timedelta(days=days)
    
    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= start_date
    ).order_by(Transaction.parsed_at.asc()).all()
    
    # 按日期聚合
    daily_data = {}
    for tx in transactions:
        date_key = tx.parsed_at.strftime("%Y-%m-%d")
        if date_key not in daily_data:
            daily_data[date_key] = {"date": date_key, "income": 0, "expense": 0, "count": 0}
        if tx.transaction_type == "income":
            daily_data[date_key]["income"] += tx.amount
        else:
            daily_data[date_key]["expense"] += tx.amount
        daily_data[date_key]["count"] += 1
    
    # 补充没有交易的日期
    result = []
    current = start_date
    while current <= datetime.utcnow():
        date_key = current.strftime("%Y-%m-%d")
        if date_key in daily_data:
            result.append(daily_data[date_key])
        else:
            result.append({"date": date_key, "income": 0, "expense": 0, "count": 0})
        current += timedelta(days=1)
    
    # 分类统计
    category_stats = {}
    for tx in transactions:
        if tx.transaction_type == "expense":
            cat = tx.category or "其他"
            if cat not in category_stats:
                category_stats[cat] = 0
            category_stats[cat] += tx.amount
    
    # 排序取前 8 类
    categories = sorted(category_stats.items(), key=lambda x: x[1], reverse=True)[:8]
    
    return {
        "daily": result,
        "categories": [{"name": k, "amount": v} for k, v in categories],
        "total_expense": sum(d["expense"] for d in result),
        "total_income": sum(d["income"] for d in result),
    }


@router.get("/stats/monthly")
async def get_monthly_report(year: int = None, month: int = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """月度收支汇总报表"""
    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month
    
    start = datetime(y, m, 1)
    if m == 12:
        end = datetime(y + 1, 1, 1)
    else:
        end = datetime(y, m + 1, 1)
    
    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= start,
        Transaction.parsed_at < end
    ).all()
    
    total_income = sum(t.amount for t in transactions if t.transaction_type == "income")
    total_expense = sum(t.amount for t in transactions if t.transaction_type == "expense")
    
    # 分类统计
    income_cats = {}
    expense_cats = {}
    for t in transactions:
        cat = t.category or "其他"
        if t.transaction_type == "income":
            income_cats[cat] = income_cats.get(cat, 0) + t.amount
        else:
            expense_cats[cat] = expense_cats.get(cat, 0) + t.amount
    
    # 日均
    days_in_month = (end - start).days
    daily_avg_expense = total_expense / days_in_month if days_in_month > 0 else 0
    
    # 周对比
    weeks = []
    for w in range(4):
        w_start = start + timedelta(days=w * 7)
        w_end = min(w_start + timedelta(days=7), end)
        w_txs = [t for t in transactions if w_start <= t.parsed_at < w_end]
        weeks.append({
            "week": w + 1,
            "income": sum(t.amount for t in w_txs if t.transaction_type == "income"),
            "expense": sum(t.amount for t in w_txs if t.transaction_type == "expense"),
            "count": len(w_txs)
        })
    
    return {
        "year": y,
        "month": m,
        "total_income": total_income,
        "total_expense": total_expense,
        "net": total_income - total_expense,
        "savings_rate": round((total_income - total_expense) / total_income * 100, 1) if total_income > 0 else 0,
        "daily_avg_expense": round(daily_avg_expense, 2),
        "transaction_count": len(transactions),
        "income_categories": sorted([{"name": k, "amount": v} for k, v in income_cats.items()], key=lambda x: -x["amount"]),
        "expense_categories": sorted([{"name": k, "amount": v} for k, v in expense_cats.items()], key=lambda x: -x["amount"]),
        "weekly": weeks
    }


# ===== 报表 API =====


@router.get("/stats/daily")
async def get_daily_report(date: str = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """日报：每日消费汇总"""
    if date:
        target = datetime.strptime(date, "%Y-%m-%d")
    else:
        target = datetime.utcnow()
    
    day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    
    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= day_start,
        Transaction.parsed_at < day_end
    ).all()
    
    total_income = sum(t.amount for t in transactions if t.transaction_type == "income")
    total_expense = sum(t.amount for t in transactions if t.transaction_type == "expense")
    
    cats = {}
    for t in transactions:
        cat = t.category or "其他"
        if t.transaction_type == "expense":
            cats[cat] = cats.get(cat, 0) + t.amount
    
    return {
        "date": day_start.strftime("%Y-%m-%d"),
        "total_income": total_income,
        "total_expense": total_expense,
        "net": total_income - total_expense,
        "transaction_count": len(transactions),
        "categories": sorted([{"name": k, "amount": v} for k, v in cats.items()], key=lambda x: -x["amount"]),
        "transactions": [{"amount": t.amount, "category": t.category, "description": t.description, "type": t.transaction_type} for t in transactions]
    }


@router.get("/stats/weekly")
async def get_weekly_report(week_offset: int = 0, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """周报：趋势分析"""
    now = datetime.utcnow()
    # 本周一
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = monday - timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=7)
    
    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= week_start,
        Transaction.parsed_at < week_end
    ).all()
    
    total_income = sum(t.amount for t in transactions if t.transaction_type == "income")
    total_expense = sum(t.amount for t in transactions if t.transaction_type == "expense")
    
    # 按天分组
    daily = []
    for d in range(7):
        d_start = week_start + timedelta(days=d)
        d_end = d_start + timedelta(days=1)
        d_txs = [t for t in transactions if d_start <= t.parsed_at < d_end]
        daily.append({
            "date": d_start.strftime("%Y-%m-%d"),
            "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][d],
            "income": sum(t.amount for t in d_txs if t.transaction_type == "income"),
            "expense": sum(t.amount for t in d_txs if t.transaction_type == "expense"),
            "count": len(d_txs)
        })
    
    cats = {}
    for t in transactions:
        cat = t.category or "其他"
        if t.transaction_type == "expense":
            cats[cat] = cats.get(cat, 0) + t.amount
    
    return {
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": week_end.strftime("%Y-%m-%d"),
        "total_income": total_income,
        "total_expense": total_expense,
        "net": total_income - total_expense,
        "daily_avg_expense": round(total_expense / 7, 2) if total_expense else 0,
        "transaction_count": len(transactions),
        "daily": daily,
        "categories": sorted([{"name": k, "amount": v} for k, v in cats.items()], key=lambda x: -x["amount"]),
    }


@router.get("/stats/yearly")
async def get_yearly_report(year: int = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """年报：年度总结"""
    now = datetime.utcnow()
    y = year or now.year
    
    year_start = datetime(y, 1, 1)
    year_end = datetime(y + 1, 1, 1)
    
    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= year_start,
        Transaction.parsed_at < year_end
    ).all()
    
    total_income = sum(t.amount for t in transactions if t.transaction_type == "income")
    total_expense = sum(t.amount for t in transactions if t.transaction_type == "expense")
    
    # 按月分组
    monthly = []
    for m in range(1, 13):
        m_start = datetime(y, m, 1)
        m_end = datetime(y, m + 1, 1) if m < 12 else datetime(y + 1, 1, 1)
        m_txs = [t for t in transactions if m_start <= t.parsed_at < m_end]
        monthly.append({
            "month": m,
            "income": sum(t.amount for t in m_txs if t.transaction_type == "income"),
            "expense": sum(t.amount for t in m_txs if t.transaction_type == "expense"),
            "count": len(m_txs)
        })
    
    cats = {}
    for t in transactions:
        cat = t.category or "其他"
        if t.transaction_type == "expense":
            cats[cat] = cats.get(cat, 0) + t.amount
    
    return {
        "year": y,
        "total_income": total_income,
        "total_expense": total_expense,
        "net": total_income - total_expense,
        "savings_rate": round((total_income - total_expense) / total_income * 100, 1) if total_income > 0 else 0,
        "monthly_avg_expense": round(total_expense / 12, 2) if total_expense else 0,
        "transaction_count": len(transactions),
        "monthly": monthly,
        "categories": sorted([{"name": k, "amount": v} for k, v in cats.items()], key=lambda x: -x["amount"])[:10],
    }


@router.get("/stats/asset-curve")
async def get_asset_curve(months: int = 12, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """资产变化曲线数据"""
    now = datetime.utcnow()
    start = now - timedelta(days=months * 30)
    
    # 当前总资产
    current_assets = db.query(func.coalesce(func.sum(Asset.current_value), 0)).scalar() or 0.0
    current_liabilities = db.query(func.coalesce(func.sum(Liability.current_amount), 0)).scalar() or 0.0
    current_net = current_assets - current_liabilities
    
    # 历史净资产（按月推算）
    curve = []
    for i in range(months, -1, -1):
        m_end = now - timedelta(days=i * 30)
        m_start = m_end - timedelta(days=30)
        
        # 收入支出累计
        period_income = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.transaction_type == "income",
            Transaction.parsed_at < m_end
        ).scalar() or 0.0
        
        period_expense = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.transaction_type == "expense",
            Transaction.parsed_at < m_end
        ).scalar() or 0.0
        
        estimated_net = current_net - (period_income - period_expense) * 0  # 简化：用当前值
        curve.append({
            "month": m_end.strftime("%Y-%m"),
            "estimated_net": round(current_net - (total_expense_so_far(db, m_end) - total_income_so_far(db, m_end)), 2),
            "cumulative_income": round(float(period_income), 2),
            "cumulative_expense": round(float(period_expense), 2),
        })
    
    return {
        "current_net_worth": round(current_net, 2),
        "current_assets": round(float(current_assets), 2),
        "current_liabilities": round(float(current_liabilities), 2),
        "months": months,
        "curve": curve
    }


def total_expense_so_far(db, end_date):
    return float(db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.transaction_type == "expense",
        Transaction.parsed_at < end_date
    ).scalar() or 0)

def total_income_so_far(db, end_date):
    return float(db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.transaction_type == "income",
        Transaction.parsed_at < end_date
    ).scalar() or 0)


# ===== 数据导入导出 =====
