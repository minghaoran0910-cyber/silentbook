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

@router.get("/cashflow/calendar")
async def get_cashflow_calendar(
    year: Optional[int] = None,
    month: Optional[int] = None,
    account: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """现金流日历：按日展示某月的收入/支出/净现金流
    
    参数：
    - year: 年份（默认当前年）
    - month: 月份（默认当前月）
    - account: 可选，按账户筛选
    
    返回：
    - days: 每天的现金流数据（含无交易的天，金额为0）
    - summary: 月度汇总（总收入/总支出/净额/日均支出/交易笔数）
    """
    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month
    
    # 月初/月末
    month_start = datetime(y, m, 1)
    if m == 12:
        month_end = datetime(y + 1, 1, 1)
    else:
        month_end = datetime(y, m + 1, 1)
    
    days_in_month = (month_end - month_start).days
    
    # 查询该月所有交易
    query = db.query(Transaction).filter(
        Transaction.parsed_at >= month_start,
        Transaction.parsed_at < month_end
    )
    if account:
        query = query.filter(Transaction.account == account)
    transactions = query.all()
    
    # 按日聚合
    daily_map = {}
    for tx in transactions:
        day_key = tx.parsed_at.strftime("%Y-%m-%d")
        if day_key not in daily_map:
            daily_map[day_key] = {"income": 0.0, "expense": 0.0, "count": 0}
        if tx.transaction_type == "income":
            daily_map[day_key]["income"] += tx.amount
        else:
            daily_map[day_key]["expense"] += tx.amount
        daily_map[day_key]["count"] += 1
    
    # 构建完整日历（含无交易日）
    days = []
    total_income = 0.0
    total_expense = 0.0
    total_count = 0
    for d in range(days_in_month):
        date = month_start + timedelta(days=d)
        date_key = date.strftime("%Y-%m-%d")
        day_data = daily_map.get(date_key, {"income": 0.0, "expense": 0.0, "count": 0})
        income = round(day_data["income"], 2)
        expense = round(day_data["expense"], 2)
        net = round(income - expense, 2)
        days.append({
            "date": date_key,
            "day": d + 1,
            "weekday": date.weekday(),  # 0=周一, 6=周日
            "income": income,
            "expense": expense,
            "net": net,
            "transaction_count": day_data["count"],
        })
        total_income += day_data["income"]
        total_expense += day_data["expense"]
        total_count += day_data["count"]
    
    return {
        "year": y,
        "month": m,
        "days_in_month": days_in_month,
        "account": account,
        "days": days,
        "summary": {
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "total_net": round(total_income - total_expense, 2),
            "avg_daily_expense": round(total_expense / days_in_month, 2) if days_in_month > 0 else 0,
            "transaction_count": total_count,
            "active_days": len([d for d in days if d["transaction_count"] > 0]),
        },
    }


# ===== 现金流预测（V2-010）=====


@router.get("/cashflow/forecast")
async def get_cashflow_forecast(
    days: int = 30,
    history_days: int = 90,
    account: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """现金流预测：基于历史数据预测未来 N 天收支
    
    算法：
    1. 从历史数据中检测固定收支（同分类 + 相似金额 + 跨月出现）
    2. 非固定部分按日均摊到每天
    3. 固定收支放在典型出现日，非固定按日均叠加
    
    参数：
    - days: 预测天数（默认30）
    - history_days: 回溯天数（默认90）
    - account: 可选，按账户筛选
    """
    now = datetime.utcnow()
    history_start = now - timedelta(days=history_days)
    
    query = db.query(Transaction).filter(Transaction.parsed_at >= history_start)
    if account:
        query = query.filter(Transaction.account == account)
    transactions = query.all()
    
    if not transactions:
        return {
            "forecast_days": days,
            "history_days": history_days,
            "account": account,
            "daily_forecast": [],
            "summary": {
                "predicted_total_income": 0,
                "predicted_total_expense": 0,
                "predicted_net": 0,
                "avg_daily_income": 0,
                "avg_daily_expense": 0,
                "recurring_count": 0,
                "confidence": "low",
                "history_transaction_count": 0,
            },
            "recurring_items": [],
        }
    
    # 检测固定收支：同分类 + 相似金额(5%容差) + 跨月出现
    recurring_items = []
    non_recurring_txs = []
    
    by_category = {}
    for tx in transactions:
        cat = tx.category or "其他"
        by_category.setdefault(cat, []).append(tx)
    
    for cat, cat_txs in by_category.items():
        # 按相似金额分组
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
                non_recurring_txs.extend(cluster)
                continue
            
            # 检查是否跨月
            months = set()
            for tx in cluster:
                if tx.parsed_at:
                    months.add((tx.parsed_at.year, tx.parsed_at.month))
            
            if len(months) >= 2:
                doms = [tx.parsed_at.day for tx in cluster if tx.parsed_at]
                avg_dom_val = sum(doms) / len(doms)
                max_dev = max(abs(d - avg_dom_val) for d in doms)
                # 日方差>3天 → 不是月度固定收支
                if max_dev > 3:
                    non_recurring_txs.extend(cluster)
                    continue
                avg_amount = sum(tx.amount for tx in cluster) / len(cluster)
                avg_dom = round(avg_dom_val)
                recurring_items.append({
                    "category": cat,
                    "amount": round(avg_amount, 2),
                    "day_of_month": min(avg_dom, 28),
                    "transaction_type": cluster[0].transaction_type,
                    "occurrence_count": len(cluster),
                    "months_spanned": len(months),
                })
            else:
                non_recurring_txs.extend(cluster)
    
    # 合并用户定义的固定收支（V2-027）
    user_recurring = db.query(RecurringTransaction).filter(
        RecurringTransaction.is_active == True
    ).all()
    for rt in user_recurring:
        # 避免与自动检测重复（同分类+同类型+同日）
        already_detected = any(
            r["category"] == rt.category and
            r["transaction_type"] == rt.transaction_type and
            r["day_of_month"] == rt.day_of_month
            for r in recurring_items
        )
        if not already_detected:
            recurring_items.append({
                "category": rt.category,
                "amount": rt.amount,
                "day_of_month": rt.day_of_month,
                "transaction_type": rt.transaction_type,
                "occurrence_count": 0,  # 用户定义，无历史计数
                "months_spanned": 0,
                "source": "manual",
                "name": rt.name,
            })

    # 非固定部分按日均计算
    actual_history_days = max((now - history_start).days, 1)
    nr_income = sum(tx.amount for tx in non_recurring_txs if tx.transaction_type == "income")
    nr_expense = sum(tx.amount for tx in non_recurring_txs if tx.transaction_type == "expense")
    daily_avg_income = nr_income / actual_history_days
    daily_avg_expense = nr_expense / actual_history_days
    
    # 构建预测：从明天起 N 天
    daily_forecast = []
    total_pred_income = 0.0
    total_pred_expense = 0.0
    
    for d in range(days):
        forecast_date = now + timedelta(days=d + 1)
        date_key = forecast_date.strftime("%Y-%m-%d")
        dom = forecast_date.day
        
        pred_income = daily_avg_income
        pred_expense = daily_avg_expense
        rec_income = 0.0
        rec_expense = 0.0
        
        for item in recurring_items:
            if item["day_of_month"] == dom:
                if item["transaction_type"] == "income":
                    pred_income += item["amount"]
                    rec_income += item["amount"]
                else:
                    pred_expense += item["amount"]
                    rec_expense += item["amount"]
        
        pred_income = round(pred_income, 2)
        pred_expense = round(pred_expense, 2)
        
        daily_forecast.append({
            "date": date_key,
            "day": dom,
            "weekday": forecast_date.weekday(),
            "predicted_income": pred_income,
            "predicted_expense": pred_expense,
            "predicted_net": round(pred_income - pred_expense, 2),
            "recurring_income": round(rec_income, 2),
            "recurring_expense": round(rec_expense, 2),
        })
        total_pred_income += pred_income
        total_pred_expense += pred_expense
    
    # 置信度：基于数据量
    tx_count = len(transactions)
    if tx_count >= 50 and history_days >= 60:
        confidence = "high"
    elif tx_count >= 20 and history_days >= 30:
        confidence = "medium"
    else:
        confidence = "low"
    
    return {
        "forecast_days": days,
        "history_days": history_days,
        "account": account,
        "daily_forecast": daily_forecast,
        "summary": {
            "predicted_total_income": round(total_pred_income, 2),
            "predicted_total_expense": round(total_pred_expense, 2),
            "predicted_net": round(total_pred_income - total_pred_expense, 2),
            "avg_daily_income": round(daily_avg_income, 2),
            "avg_daily_expense": round(daily_avg_expense, 2),
            "recurring_count": len(recurring_items),
            "confidence": confidence,
            "history_transaction_count": tx_count,
        },
        "recurring_items": recurring_items,
    }


# ===== V2-028: 下月支出预测 =====


@router.get("/forecast/next-month")
async def get_next_month_forecast(
    lookback_months: int = 6,
    account: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """下月支出预测：基于历史月度趋势预测下月各类别支出
    
    算法：
    1. 统计过去 N 个月各分类的月度支出
    2. 对每个分类做线性回归检测趋势（增长/下降/稳定）
    3. 用回归方程预测下月金额
    4. 合并用户定义的固定收支（V2-027）
    5. 计算置信度（基于数据量和波动性）
    
    返回：
    - 下月预测总额
    - 各分类预测明细 + 趋势方向
    - 与本月/上月的对比
    - 固定收支列表
    """
    from datetime import datetime, timedelta
    import math
    
    now = datetime.utcnow()
    # 计算下个月的第一天
    if now.month == 12:
        next_month_start = datetime(now.year + 1, 1, 1)
    else:
        next_month_start = datetime(now.year, now.month + 1, 1)
    next_month_end = datetime(now.year + (1 if now.month == 12 else 0), 
                               (now.month % 12) + 1, 1)
    # 回推 lookback_months 个月
    start_month = now.month - lookback_months
    start_year = now.year
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    history_start = datetime(start_year, start_month, 1)
    
    # 获取历史支出
    query = db.query(Transaction).filter(
        Transaction.parsed_at >= history_start,
        Transaction.transaction_type == "expense"
    )
    if account:
        query = query.filter(Transaction.account == account)
    transactions = query.all()
    
    if not transactions:
        return {
            "forecast_month": next_month_start.strftime("%Y-%m"),
            "lookback_months": lookback_months,
            "total_predicted": 0,
            "categories": [],
            "recurring_items": [],
            "comparison": {
                "current_month": 0,
                "last_month": 0,
                "change_percent": 0,
            },
            "confidence": "low",
            "history_months": 0,
            "trend_summary": {"increasing": 0, "stable": 0, "decreasing": 0},
        }
    
    # 按月份和分类汇总
    monthly_category = {}  # {(year, month): {category: total}}
    for tx in transactions:
        if tx.parsed_at:
            ym = (tx.parsed_at.year, tx.parsed_at.month)
            cat = tx.category or "其他"
            monthly_category.setdefault(ym, {})
            monthly_category[ym][cat] = monthly_category[ym].get(cat, 0) + tx.amount
    
    # 获取所有分类
    all_categories = set()
    for month_data in monthly_category.values():
        all_categories.update(month_data.keys())
    
    # 生成月份序列（用于回归）
    sorted_months = sorted(monthly_category.keys())
    month_to_idx = {ym: i for i, ym in enumerate(sorted_months)}
    
    # 当前月和上月的实际支出
    current_ym = (now.year, now.month)
    last_ym = (now.year - (1 if now.month == 1 else 0), 
               (now.month - 1) if now.month > 1 else 12)
    current_month_total = sum(monthly_category.get(current_ym, {}).values())
    last_month_total = sum(monthly_category.get(last_ym, {}).values())
    
    # 对每个分类做线性回归预测
    categories_forecast = []
    total_predicted = 0.0
    trend_counts = {"increasing": 0, "stable": 0, "decreasing": 0}
    
    for cat in sorted(all_categories):
        # 收集该分类的月度数据（只包含该分类有数据的月份）
        cat_monthly = []
        for ym in sorted_months:
            amt = monthly_category.get(ym, {}).get(cat, 0)
            if amt > 0:
                cat_monthly.append((month_to_idx[ym], amt))
        monthly_amounts = cat_monthly
        
        n = len(monthly_amounts)
        if n == 0:
            continue
        
        # 线性回归: y = a + b*x
        sum_x = sum(x for x, _ in monthly_amounts)
        sum_y = sum(y for _, y in monthly_amounts)
        sum_xy = sum(x * y for x, y in monthly_amounts)
        sum_x2 = sum(x * x for x, _ in monthly_amounts)
        
        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            # 只有一个数据点或所有 x 相同
            slope = 0
            intercept = sum_y / n
        else:
            slope = (n * sum_xy - sum_x * sum_y) / denom
            intercept = (sum_y - slope * sum_x) / n
        
        # 预测下月（x = n，即下一个索引）
        predicted = intercept + slope * n
        predicted = max(predicted, 0)  # 不能为负
        
        # 计算均值和标准差（用于置信度）
        amounts = [y for _, y in monthly_amounts]
        mean_amt = sum(amounts) / n
        if n > 1:
            variance = sum((a - mean_amt) ** 2 for a in amounts) / (n - 1)
            std_dev = math.sqrt(variance)
            cv = std_dev / mean_amt if mean_amt > 0 else 999  # 变异系数
        else:
            std_dev = 0
            cv = 0
        
        # 趋势判断（基于斜率相对均值的比例）
        if mean_amt > 0:
            trend_ratio = slope / mean_amt
            if trend_ratio > 0.05:  # 月增长>5%
                trend = "increasing"
                trend_label = "↑ 增长"
            elif trend_ratio < -0.05:  # 月下降>5%
                trend = "decreasing"
                trend_label = "↓ 下降"
            else:
                trend = "stable"
                trend_label = "→ 稳定"
        else:
            trend = "stable"
            trend_label = "→ 稳定"
        
        trend_counts[trend] += 1
        
        # 单分类置信度
        if n >= 3 and cv < 0.5:
            cat_confidence = "high"
        elif n >= 2 and cv < 1.0:
            cat_confidence = "medium"
        else:
            cat_confidence = "low"
        
        # 本月实际值
        current_cat_amount = monthly_category.get(current_ym, {}).get(cat, 0)
        last_cat_amount = monthly_category.get(last_ym, {}).get(cat, 0)
        
        categories_forecast.append({
            "category": cat,
            "predicted_amount": round(predicted, 2),
            "trend": trend,
            "trend_label": trend_label,
            "slope": round(slope, 2),  # 每月变化量
            "avg_monthly": round(mean_amt, 2),
            "std_dev": round(std_dev, 2),
            "confidence": cat_confidence,
            "data_months": n,
            "current_month": round(current_cat_amount, 2),
            "last_month": round(last_cat_amount, 2),
            "history": [
                {"month": f"{ym[0]}-{ym[1]:02d}", "amount": round(monthly_category.get(ym, {}).get(cat, 0), 2)}
                for ym in sorted_months
            ],
        })
        total_predicted += predicted
    
    # 合并用户定义的固定收支（V2-027）
    recurring_items = []
    user_recurring = db.query(RecurringTransaction).filter(
        RecurringTransaction.is_active == True,
        RecurringTransaction.transaction_type == "expense"
    ).all()
    
    next_month_num = next_month_start.month
    for rt in user_recurring:
        # 根据频率判断下月是否会发生
        will_occur = False
        if rt.frequency == "monthly":
            will_occur = True
        elif rt.frequency == "daily":
            will_occur = True
        elif rt.frequency == "weekly":
            will_occur = True
        elif rt.frequency == "biweekly":
            will_occur = True
        elif rt.frequency == "quarterly":
            will_occur = (next_month_num - 1) % 3 == 0
        elif rt.frequency == "yearly":
            will_occur = next_month_num == 1
        
        if will_occur:
            # 检查是否已在分类预测中（同分类）
            already_included = any(
                cf["category"] == rt.category for cf in categories_forecast
            )
            recurring_items.append({
                "name": rt.name,
                "category": rt.category,
                "amount": rt.amount,
                "day_of_month": rt.day_of_month,
                "frequency": rt.frequency,
                "already_in_forecast": already_included,
            })
            if not already_included:
                total_predicted += rt.amount
    
    # 按预测金额降序排列
    categories_forecast.sort(key=lambda x: x["predicted_amount"], reverse=True)
    
    # 整体置信度
    total_months = len(sorted_months)
    total_tx_count = len(transactions)
    if total_months >= 4 and total_tx_count >= 30:
        overall_confidence = "high"
    elif total_months >= 2 and total_tx_count >= 10:
        overall_confidence = "medium"
    else:
        overall_confidence = "low"
    
    # 对比
    change_percent = 0
    if last_month_total > 0:
        change_percent = ((total_predicted - last_month_total) / last_month_total) * 100
    
    return {
        "forecast_month": next_month_start.strftime("%Y-%m"),
        "lookback_months": lookback_months,
        "total_predicted": round(total_predicted, 2),
        "categories": categories_forecast,
        "recurring_items": recurring_items,
        "comparison": {
            "current_month": round(current_month_total, 2),
            "last_month": round(last_month_total, 2),
            "predicted_vs_last_change": round(change_percent, 1),
            "predicted_vs_current_change": round(
                ((total_predicted - current_month_total) / current_month_total * 100) 
                if current_month_total > 0 else 0, 1
            ),
        },
        "confidence": overall_confidence,
        "history_months": total_months,
        "history_transactions": total_tx_count,
        "trend_summary": trend_counts,
    }


# ===== 基础报表（V2-013）=====
