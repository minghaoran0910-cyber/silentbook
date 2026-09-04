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

@router.get("/reports/monthly-summary")
async def get_monthly_summary(year: int = None, month: int = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """月度财务摘要：收入/支出/结余/储蓄率/净资产变化/账户概览/预算执行/负债概览"""
    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month

    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)

    # --- 1. 本月收支 ---
    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= start,
        Transaction.parsed_at < end
    ).all()

    total_income = sum(t.amount for t in transactions if t.transaction_type == "income")
    total_expense = sum(t.amount for t in transactions if t.transaction_type == "expense")
    net_balance = total_income - total_expense
    savings_rate = round(net_balance / total_income * 100, 1) if total_income > 0 else 0.0

    # --- 2. 净资产快照 ---
    account_total = db.query(func.coalesce(func.sum(Account.balance), 0)).filter(
        Account.status == "active"
    ).scalar() or 0.0

    asset_total = db.query(func.coalesce(func.sum(Asset.current_value), 0)).filter(
        Asset.status == "active"
    ).scalar() or 0.0

    liability_total = db.query(func.coalesce(func.sum(Liability.current_amount), 0)).filter(
        Liability.status == "active"
    ).scalar() or 0.0

    current_net_worth = account_total + asset_total - liability_total
    # 净资产变化 ≈ 本月净收支（交易驱动的财富变化）
    net_worth_change = round(net_balance, 2)

    # --- 3. 账户概览（四账户体系）---
    accounts = db.query(Account).filter(Account.status == "active").all()
    purpose_labels = {
        "consumption": "日常消费",
        "emergency": "应急储备",
        "investment": "投资增值",
        "goal": "目标储蓄",
    }
    account_summary = {"total_balance": round(sum(a.balance for a in accounts), 2), "by_purpose": {}}
    for purpose, label in purpose_labels.items():
        pa = [a for a in accounts if a.purpose == purpose]
        account_summary["by_purpose"][purpose] = {
            "label": label,
            "count": len(pa),
            "total_balance": round(sum(a.balance for a in pa), 2),
        }

    # --- 4. 预算执行 ---
    import json as _json
    raw_budgets = db.query(Setting).filter(Setting.key == "budgets").first()
    budgets = _json.loads(raw_budgets.value) if raw_budgets and raw_budgets.value else []
    budget_execution = []
    for b in budgets:
        spent = sum(t.amount for t in transactions if t.category == b["category"] and t.transaction_type == "expense")
        limit = b["monthly_limit"]
        usage = spent / limit if limit > 0 else 0.0
        budget_execution.append({
            "category": b["category"],
            "level": b.get("level", "L2"),
            "budget_limit": round(limit, 2),
            "actual_spent": round(spent, 2),
            "usage_rate": round(usage * 100, 1),
            "remaining": round(limit - spent, 2),
        })

    # --- 5. 负债概览 ---
    liabilities = db.query(Liability).filter(Liability.status == "active").all()
    liability_summary = {
        "total_debt": round(sum(l.current_amount for l in liabilities), 2),
        "monthly_payment": round(sum(l.monthly_payment for l in liabilities), 2),
        "count": len(liabilities),
    }

    # --- 6. 支出分类 ---
    expense_cats = {}
    for t in transactions:
        if t.transaction_type == "expense":
            cat = t.category or "其他"
            expense_cats[cat] = expense_cats.get(cat, 0) + t.amount
    top_expenses = sorted(
        [{"category": k, "amount": round(v, 2), "percentage": round(v / total_expense * 100, 1) if total_expense > 0 else 0.0} for k, v in expense_cats.items()],
        key=lambda x: -x["amount"]
    )[:10]

    # --- 7. 收入分类 ---
    income_cats = {}
    for t in transactions:
        if t.transaction_type == "income":
            cat = t.category or "其他"
            income_cats[cat] = income_cats.get(cat, 0) + t.amount
    top_incomes = sorted(
        [{"category": k, "amount": round(v, 2)} for k, v in income_cats.items()],
        key=lambda x: -x["amount"]
    )[:5]

    return {
        "year": y,
        "month": m,
        "period": f"{y}年{m}月",
        "total_income": round(total_income, 2),
        "total_expense": round(total_expense, 2),
        "net_balance": round(net_balance, 2),
        "savings_rate": savings_rate,
        "transaction_count": len(transactions),
        "current_net_worth": round(current_net_worth, 2),
        "net_worth_change": net_worth_change,
        "account_summary": account_summary,
        "budget_execution": budget_execution,
        "liability_summary": liability_summary,
        "top_expenses": top_expenses,
        "top_incomes": top_incomes,
    }


# ===== 基础报表（V2-014 现金流报表）=====


@router.get("/reports/cashflow")
async def get_cashflow_report(
    year: int = None,
    month: int = None,
    account: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """现金流报表：现金流入/流出/净现金流/趋势/环比/按账户分解"""
    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month

    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
    days_in_month = (end - start).days

    # --- 本月交易 ---
    query = db.query(Transaction).filter(
        Transaction.parsed_at >= start,
        Transaction.parsed_at < end
    )
    if account:
        query = query.filter(Transaction.account == account)
    transactions = query.all()

    total_inflow = sum(t.amount for t in transactions if t.transaction_type == "income")
    total_outflow = sum(t.amount for t in transactions if t.transaction_type == "expense")
    net_cashflow = total_inflow - total_outflow

    # --- 日趋势 ---
    daily_map = {}
    for tx in transactions:
        dk = tx.parsed_at.strftime("%Y-%m-%d")
        if dk not in daily_map:
            daily_map[dk] = {"inflow": 0.0, "outflow": 0.0, "count": 0}
        if tx.transaction_type == "income":
            daily_map[dk]["inflow"] += tx.amount
        else:
            daily_map[dk]["outflow"] += tx.amount
        daily_map[dk]["count"] += 1

    daily = []
    for d in range(days_in_month):
        date = start + timedelta(days=d)
        dk = date.strftime("%Y-%m-%d")
        dd = daily_map.get(dk, {"inflow": 0.0, "outflow": 0.0, "count": 0})
        daily.append({
            "date": dk,
            "day": d + 1,
            "weekday": date.weekday(),
            "inflow": round(dd["inflow"], 2),
            "outflow": round(dd["outflow"], 2),
            "net": round(dd["inflow"] - dd["outflow"], 2),
            "transaction_count": dd["count"],
        })

    # --- 环比（上月）---
    prev_end = start
    prev_start = datetime(y, m - 1, 1) if m > 1 else datetime(y - 1, 12, 1)
    prev_query = db.query(Transaction).filter(
        Transaction.parsed_at >= prev_start,
        Transaction.parsed_at < prev_end
    )
    if account:
        prev_query = prev_query.filter(Transaction.account == account)
    prev_txs = prev_query.all()
    prev_inflow = sum(t.amount for t in prev_txs if t.transaction_type == "income")
    prev_outflow = sum(t.amount for t in prev_txs if t.transaction_type == "expense")
    prev_net = prev_inflow - prev_outflow
    prev_days = (prev_end - prev_start).days

    comparison = {
        "prev_period": f"{prev_start.year}年{prev_start.month}月",
        "prev_inflow": round(prev_inflow, 2),
        "prev_outflow": round(prev_outflow, 2),
        "prev_net": round(prev_net, 2),
        "inflow_change": round(total_inflow - prev_inflow, 2),
        "outflow_change": round(total_outflow - prev_outflow, 2),
        "net_change": round(net_cashflow - prev_net, 2),
        "inflow_change_pct": round((total_inflow - prev_inflow) / prev_inflow * 100, 1) if prev_inflow > 0 else 0.0,
        "outflow_change_pct": round((total_outflow - prev_outflow) / prev_outflow * 100, 1) if prev_outflow > 0 else 0.0,
    }

    # --- 按账户分解 ---
    by_account = {}
    for tx in transactions:
        acc = tx.account or "未分类"
        if acc not in by_account:
            by_account[acc] = {"inflow": 0.0, "outflow": 0.0, "count": 0}
        if tx.transaction_type == "income":
            by_account[acc]["inflow"] += tx.amount
        else:
            by_account[acc]["outflow"] += tx.amount
        by_account[acc]["count"] += 1
    account_breakdown = [
        {"account": k, "inflow": round(v["inflow"], 2), "outflow": round(v["outflow"], 2),
         "net": round(v["inflow"] - v["outflow"], 2), "count": v["count"]}
        for k, v in sorted(by_account.items(), key=lambda x: -(x[1]["inflow"] + x[1]["outflow"]))
    ]

    # --- 累计净现金流（年初至今）---
    year_start = datetime(y, 1, 1)
    ytd_query = db.query(Transaction).filter(
        Transaction.parsed_at >= year_start,
        Transaction.parsed_at < end
    )
    if account:
        ytd_query = ytd_query.filter(Transaction.account == account)
    ytd_txs = ytd_query.all()
    ytd_inflow = sum(t.amount for t in ytd_txs if t.transaction_type == "income")
    ytd_outflow = sum(t.amount for t in ytd_txs if t.transaction_type == "expense")

    return {
        "year": y,
        "month": m,
        "period": f"{y}年{m}月",
        "account": account,
        "total_inflow": round(total_inflow, 2),
        "total_outflow": round(total_outflow, 2),
        "net_cashflow": round(net_cashflow, 2),
        "avg_daily_inflow": round(total_inflow / days_in_month, 2) if days_in_month > 0 else 0,
        "avg_daily_outflow": round(total_outflow / days_in_month, 2) if days_in_month > 0 else 0,
        "transaction_count": len(transactions),
        "active_days": len([d for d in daily if d["transaction_count"] > 0]),
        "daily": daily,
        "comparison": comparison,
        "account_breakdown": account_breakdown,
        "ytd": {
            "inflow": round(ytd_inflow, 2),
            "outflow": round(ytd_outflow, 2),
            "net": round(ytd_inflow - ytd_outflow, 2),
        },
    }


# ===== 基础报表（V2-015 资产负债表）=====

# 资产类型中文标签


ASSET_TYPE_LABELS = {
    "cash": "现金",
    "savings": "存款",
    "fund": "基金",
    "stock": "股票",
    "bond": "债券",
    "property": "房产",
    "other": "其他",
}

# 负债类型中文标签（复用 V2-011 定义的 LIABI_LIABILITY_TYPE_LABELS）


@router.get("/reports/balance-sheet")
async def get_balance_sheet(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """资产负债表：资产/负债/净资产/资产负债率/分类明细"""
    # --- 资产 ---
    assets = db.query(Asset).filter(Asset.status == "active").all()
    asset_by_type = {}
    for a in assets:
        t = a.asset_type if a.asset_type in ASSET_TYPE_LABELS else "other"
        if t not in asset_by_type:
            asset_by_type[t] = {"label": ASSET_TYPE_LABELS[t], "items": [], "total_value": 0.0, "count": 0}
        asset_by_type[t]["items"].append({
            "id": a.id, "name": a.name, "current_value": a.current_value,
            "initial_value": a.initial_value,
            "gain_loss": round(a.current_value - a.initial_value, 2) if a.initial_value else 0.0,
            "gain_loss_pct": round((a.current_value - a.initial_value) / a.initial_value * 100, 1) if a.initial_value and a.initial_value > 0 else 0.0,
            "liquidity": a.liquidity,
            "account": a.account,
        })
        asset_by_type[t]["total_value"] += a.current_value
        asset_by_type[t]["count"] += 1

    total_assets = sum(a.current_value for a in assets)

    # --- 负债 ---
    liabilities = db.query(Liability).filter(Liability.status == "active").all()
    liab_by_type = {}
    for l in liabilities:
        t = l.liability_type if l.liability_type in LIABILITY_TYPE_LABELS else "other"
        if t not in liab_by_type:
            liab_by_type[t] = {"label": LIABILITY_TYPE_LABELS[t], "items": [], "total_amount": 0.0, "count": 0}
        liab_by_type[t]["items"].append({
            "id": l.id, "name": l.name,
            "total_amount": l.total_amount, "current_amount": l.current_amount,
            "interest_rate": l.interest_rate,
            "monthly_payment": l.monthly_payment,
            "remaining_periods": l.remaining_periods,
            "due_date": str(l.due_date) if l.due_date else None,
        })
        liab_by_type[t]["total_amount"] += l.current_amount
        liab_by_type[t]["count"] += 1

    total_liabilities = sum(l.current_amount for l in liabilities)
    net_worth = total_assets - total_liabilities
    debt_ratio = round(total_liabilities / total_assets * 100, 1) if total_assets > 0 else 0.0

    # --- 账户余额（四账户体系）---
    accounts = db.query(Account).filter(Account.status == "active").all()
    total_account_balance = sum(a.balance for a in accounts)

    # --- 健康指标 ---
    if total_assets == 0 and total_liabilities == 0:
        health_status = "empty"
        health_message = "无资产和负债数据"
    elif debt_ratio < 30:
        health_status = "healthy"
        health_message = "资产负债率健康"
    elif debt_ratio < 50:
        health_status = "normal"
        health_message = "资产负债率正常"
    elif debt_ratio < 70:
        health_status = "warning"
        health_message = "资产负债率偏高，建议关注"
    else:
        health_status = "danger"
        health_message = "资产负债率过高，存在风险"

    return {
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "total_assets": round(total_assets, 2),
        "total_liabilities": round(total_liabilities, 2),
        "net_worth": round(net_worth, 2),
        "total_account_balance": round(total_account_balance, 2),
        "total_net_worth": round(net_worth + total_account_balance, 2),
        "debt_ratio": debt_ratio,
        "health_status": health_status,
        "health_message": health_message,
        "assets_by_type": {k: {**v, "total_value": round(v["total_value"], 2)} for k, v in asset_by_type.items()},
        "liabilities_by_type": {k: {**v, "total_amount": round(v["total_amount"], 2)} for k, v in liab_by_type.items()},
        "asset_count": len(assets),
        "liability_count": len(liabilities),
        "account_count": len(accounts),
    }


# ===== 高级报表（V2-021 预算执行报表）=====


@router.get("/reports/budget-execution")
async def get_budget_execution_report(
    year: int = None,
    month: int = None,
    months: int = 3,
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """预算执行报表：各分类预算vs实际/偏差率/按级别汇总/趋势/预警"""
    import json as _json

    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month
    months = max(1, min(months, 12))

    # --- 读取预算配置 ---
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    budgets = _json.loads(raw.value) if raw and raw.value else []
    if not budgets:
        return {
            "year": y, "month": m,
            "summary": {"total_budget": 0, "total_spent": 0, "remaining": 0,
                        "execution_rate": 0, "days_elapsed": 0, "days_in_month": 0,
                        "daily_budget": 0, "daily_actual": 0, "projected_usage": 0},
            "by_category": [], "by_level": {}, "trend": [], "alerts": [],
            "unbudgeted_categories": [],
            "message": "未设置预算，请先创建预算或使用预算模板",
        }

    # 补全 level 字段
    for b in budgets:
        if "level" not in b:
            b["level"] = DEFAULT_CATEGORY_LEVELS.get(b.get("category", ""), "L2")

    # --- 计算当月时间范围 ---
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
    days_in_month = (end - start).days
    days_elapsed = min((now - start).days + 1, days_in_month) if (y == now.year and m == now.month) else days_in_month

    # --- 查询当月支出 ---
    month_txs = db.query(Transaction).filter(
        Transaction.transaction_type == "expense",
        Transaction.parsed_at >= start,
        Transaction.parsed_at < end,
    ).all()

    actual_by_cat = {}
    for tx in month_txs:
        cat = tx.category or "其他"
        actual_by_cat[cat] = actual_by_cat.get(cat, 0) + tx.amount

    # --- 1. 按分类明细 ---
    by_category = []
    total_budget = 0
    total_spent = 0
    budgeted_cats = set()

    for b in budgets:
        cat = b["category"]
        budgeted_cats.add(cat)
        limit = b["monthly_limit"]
        spent = actual_by_cat.get(cat, 0)
        remaining = limit - spent
        usage_rate = spent / limit if limit > 0 else 0
        deviation = spent - limit
        deviation_rate = (spent - limit) / limit * 100 if limit > 0 else 0
        alert_info = get_alert_level(usage_rate, b.get("alert_thresholds"))

        total_budget += limit
        total_spent += spent

        by_category.append({
            "category": cat,
            "level": b["level"],
            "level_label": LEVEL_LABELS.get(b["level"], "改善支出"),
            "budget_limit": round(limit, 2),
            "actual_spent": round(spent, 2),
            "remaining": round(remaining, 2),
            "usage_rate": round(usage_rate * 100, 1),
            "deviation": round(deviation, 2),
            "deviation_rate": round(deviation_rate, 1),
            "alert_level": alert_info["level"],
            "alert_name": alert_info["name"],
            "alert_color": alert_info["color"],
        })

    # 按偏差率降序排列（超支最多的排前面）
    by_category.sort(key=lambda x: -x["deviation_rate"])

    # --- 2. 未设预算但有支出的分类 ---
    unbudgeted = []
    for cat, amt in actual_by_cat.items():
        if cat not in budgeted_cats:
            unbudgeted.append({
                "category": cat,
                "actual_spent": round(amt, 2),
                "level": DEFAULT_CATEGORY_LEVELS.get(cat, "L2"),
                "level_label": LEVEL_LABELS.get(DEFAULT_CATEGORY_LEVELS.get(cat, "L2"), "改善支出"),
            })
    unbudgeted.sort(key=lambda x: -x["actual_spent"])

    # --- 3. 按级别汇总 ---
    by_level = {}
    for level in ["L1", "L2", "L3"]:
        level_budgets = [b for b in budgets if b.get("level") == level]
        level_limit = sum(b["monthly_limit"] for b in level_budgets)
        level_spent = sum(actual_by_cat.get(b["category"], 0) for b in level_budgets)
        # 加上未设预算但属于该级别的支出
        level_budgeted_cats = {b["category"] for b in level_budgets}
        for cat, amt in actual_by_cat.items():
            if cat not in budgeted_cats and DEFAULT_CATEGORY_LEVELS.get(cat, "L2") == level:
                level_spent += amt
        level_remaining = level_limit - level_spent
        level_usage = level_spent / level_limit if level_limit > 0 else 0

        by_level[level] = {
            "label": LEVEL_LABELS[level],
            "compressibility": LEVEL_COMPRESSIBILITY[level],
            "budget_limit": round(level_limit, 2),
            "actual_spent": round(level_spent, 2),
            "remaining": round(level_remaining, 2),
            "usage_rate": round(level_usage * 100, 1),
            "deviation": round(level_spent - level_limit, 2),
            "deviation_rate": round((level_spent - level_limit) / level_limit * 100, 1) if level_limit > 0 else 0,
            "category_count": len(level_budgets),
        }

    # --- 4. 趋势分析（过去 N 个月） ---
    trend = []
    for i in range(months - 1, -1, -1):
        # 计算目标月份
        tm = m - i
        ty = y
        while tm <= 0:
            tm += 12
            ty -= 1

        t_start = datetime(ty, tm, 1)
        t_end = datetime(ty + 1, 1, 1) if tm == 12 else datetime(ty, tm + 1, 1)
        t_days = (t_end - t_start).days

        # 该月支出
        t_txs = db.query(Transaction).filter(
            Transaction.transaction_type == "expense",
            Transaction.parsed_at >= t_start,
            Transaction.parsed_at < t_end,
        ).all()
        t_actual_by_cat = {}
        for tx in t_txs:
            c = tx.category or "其他"
            t_actual_by_cat[c] = t_actual_by_cat.get(c, 0) + tx.amount

        t_total_spent = 0
        t_cat_count = 0
        t_over_count = 0
        for b in budgets:
            spent = t_actual_by_cat.get(b["category"], 0)
            t_total_spent += spent
            if spent > b["monthly_limit"]:
                t_over_count += 1
            t_cat_count += 1

        t_execution = round(t_total_spent / total_budget * 100, 1) if total_budget > 0 else 0
        trend.append({
            "year": ty, "month": tm,
            "period": f"{ty}年{tm}月",
            "total_budget": round(total_budget, 2),
            "total_spent": round(t_total_spent, 2),
            "execution_rate": t_execution,
            "over_budget_count": t_over_count,
            "total_categories": t_cat_count,
            "days_in_month": t_days,
        })

    # --- 5. 预警列表 ---
    alerts = []
    for item in by_category:
        if item["alert_level"] >= 3:  # 提醒及以上
            alerts.append({
                "category": item["category"],
                "level": item["level"],
                "alert_level": item["alert_level"],
                "alert_name": item["alert_name"],
                "alert_color": item["alert_color"],
                "usage_rate": item["usage_rate"],
                "deviation": item["deviation"],
                "message": f"{item['category']}已用{item['usage_rate']}%，{'超支' if item['usage_rate'] > 100 else '接近预算上限'}",
            })
    # 按告警级别降序
    alerts.sort(key=lambda x: -x["alert_level"])

    # --- 6. 汇总 ---
    remaining = total_budget - total_spent
    execution_rate = round(total_spent / total_budget * 100, 1) if total_budget > 0 else 0
    daily_budget = round(total_budget / days_in_month, 2) if days_in_month > 0 else 0
    daily_actual = round(total_spent / days_elapsed, 2) if days_elapsed > 0 else 0
    # 预测本月使用率（按已过天数线性外推）
    projected_usage = round(daily_actual * days_in_month / total_budget * 100, 1) if total_budget > 0 and days_elapsed > 0 else 0

    return {
        "year": y,
        "month": m,
        "period": f"{y}年{m}月",
        "summary": {
            "total_budget": round(total_budget, 2),
            "total_spent": round(total_spent, 2),
            "remaining": round(remaining, 2),
            "execution_rate": execution_rate,
            "days_elapsed": days_elapsed,
            "days_in_month": days_in_month,
            "daily_budget": daily_budget,
            "daily_actual": daily_actual,
            "projected_usage": projected_usage,
            "budget_count": len(budgets),
            "over_budget_count": sum(1 for c in by_category if c["usage_rate"] > 100),
        },
        "by_category": by_category,
        "by_level": by_level,
        "trend": trend,
        "alerts": alerts,
        "unbudgeted_categories": unbudgeted,
    }


# ===== V2-022 支出结构报表 =====

# 结构健康度基准（L1/L2/L3 理想占比）


STRUCTURE_BENCHMARKS = {
    "L1": {"ideal_min": 0.35, "ideal_max": 0.55, "label": "必要支出"},
    "L2": {"ideal_min": 0.20, "ideal_max": 0.35, "label": "改善支出"},
    "L3": {"ideal_min": 0.00, "ideal_max": 0.20, "label": "非必要支出"},
}


def _classify_expense_structure(total: float, l1: float, l2: float, l3: float) -> dict:
    """评估支出结构健康度"""
    if total <= 0:
        return {"level": "empty", "label": "暂无数据", "color": "gray", "score": 0, "suggestions": []}

    l1_pct = l1 / total
    l2_pct = l2 / total
    l3_pct = l3 / total

    # 评分：每级在理想区间得满分，偏离扣分
    score = 0
    suggestions = []

    # L1 评分（40分）
    if STRUCTURE_BENCHMARKS["L1"]["ideal_min"] <= l1_pct <= STRUCTURE_BENCHMARKS["L1"]["ideal_max"]:
        score += 40
    elif l1_pct < STRUCTURE_BENCHMARKS["L1"]["ideal_min"]:
        score += max(0, 40 - int((STRUCTURE_BENCHMARKS["L1"]["ideal_min"] - l1_pct) * 200))
    else:
        score += max(0, 40 - int((l1_pct - STRUCTURE_BENCHMARKS["L1"]["ideal_max"]) * 200))
        suggestions.append(f"必要支出占比 {l1_pct:.0%} 偏高，检查是否有可归入改善类的支出")

    # L3 评分（35分）— 非必要越低越好
    if l3_pct <= STRUCTURE_BENCHMARKS["L3"]["ideal_max"]:
        score += 35
    elif l3_pct <= 0.30:
        score += 20
        suggestions.append(f"非必要支出占比 {l3_pct:.0%}，建议控制在 20% 以内")
    elif l3_pct <= 0.40:
        score += 10
        suggestions.append(f"非必要支出占比 {l3_pct:.0%} 偏高，优先削减娱乐/购物类")
    else:
        suggestions.append(f"⚠️ 非必要支出占比 {l3_pct:.0%} 严重超标，建议立即审视消费习惯")

    # L2 评分（25分）
    if STRUCTURE_BENCHMARKS["L2"]["ideal_min"] <= l2_pct <= STRUCTURE_BENCHMARKS["L2"]["ideal_max"]:
        score += 25
    elif l2_pct < STRUCTURE_BENCHMARKS["L2"]["ideal_min"]:
        score += max(0, 25 - int((STRUCTURE_BENCHMARKS["L2"]["ideal_min"] - l2_pct) * 150))
    else:
        score += max(0, 25 - int((l2_pct - STRUCTURE_BENCHMARKS["L2"]["ideal_max"]) * 150))
        suggestions.append(f"改善支出占比 {l2_pct:.0%}，部分可压缩（如订阅/会员）")

    # 综合判定
    if score >= 80:
        level, label, color = "excellent", "结构优秀", "green"
    elif score >= 65:
        level, label, color = "healthy", "结构健康", "blue"
    elif score >= 45:
        level, label, color = "warning", "结构一般", "yellow"
    else:
        level, label, color = "danger", "结构需改善", "red"

    if not suggestions:
        suggestions.append("支出结构良好，继续保持 👍")

    return {"level": level, "label": label, "color": color, "score": score, "suggestions": suggestions}


@router.get("/reports/expense-structure")
async def get_expense_structure(
    year: int = None,
    month: int = None,
    months: int = 3,
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """V2-022 支出结构报表：L1/L2/L3占比 + 分类明细 + 趋势 + 健康度评估"""
    import json as _json

    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month
    months = max(1, min(months, 12))

    # --- 读取预算配置（获取自定义 level 覆盖）---
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    budgets = _json.loads(raw.value) if raw and raw.value else []
    budget_level_map = {}  # category -> level
    for b in budgets:
        if "level" in b:
            budget_level_map[b["category"]] = b["level"]

    def _get_level(category: str) -> str:
        return budget_level_map.get(category, DEFAULT_CATEGORY_LEVELS.get(category, "L2"))

    # --- 当月支出查询 ---
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)

    month_txs = db.query(Transaction).filter(
        Transaction.transaction_type == "expense",
        Transaction.parsed_at >= start,
        Transaction.parsed_at < end,
    ).all()

    # 按级别和分类汇总
    level_amounts = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
    cat_amounts = {}  # category -> amount
    for tx in month_txs:
        cat = tx.category or "其他"
        level = _get_level(cat)
        level_amounts[level] = level_amounts.get(level, 0) + tx.amount
        cat_amounts[cat] = cat_amounts.get(cat, 0) + tx.amount

    total_expense = sum(level_amounts.values())

    # --- 按级别明细 ---
    by_level = {}
    for level in ["L1", "L2", "L3"]:
        level_cats = {c: a for c, a in cat_amounts.items() if _get_level(c) == level}
        # 按金额降序
        sorted_cats = sorted(level_cats.items(), key=lambda x: -x[1])
        categories = [
            {
                "category": cat,
                "amount": round(amt, 2),
                "percentage": round(amt / total_expense * 100, 1) if total_expense > 0 else 0,
            }
            for cat, amt in sorted_cats
        ]
        level_amt = level_amounts[level]
        by_level[level] = {
            "label": LEVEL_LABELS[level],
            "compressibility": LEVEL_COMPRESSIBILITY[level],
            "amount": round(level_amt, 2),
            "percentage": round(level_amt / total_expense * 100, 1) if total_expense > 0 else 0,
            "ideal_range": f"{STRUCTURE_BENCHMARKS[level]['ideal_min']:.0%}-{STRUCTURE_BENCHMARKS[level]['ideal_max']:.0%}",
            "categories": categories,
        }

    # --- 结构健康度 ---
    structure_health = _classify_expense_structure(
        total_expense, level_amounts["L1"], level_amounts["L2"], level_amounts["L3"]
    )

    # --- 趋势分析（过去 N 个月）---
    trend = []
    for i in range(months - 1, -1, -1):
        tm = m - i
        ty = y
        while tm <= 0:
            tm += 12
            ty -= 1

        t_start = datetime(ty, tm, 1)
        t_end = datetime(ty + 1, 1, 1) if tm == 12 else datetime(ty, tm + 1, 1)

        t_txs = db.query(Transaction).filter(
            Transaction.transaction_type == "expense",
            Transaction.parsed_at >= t_start,
            Transaction.parsed_at < t_end,
        ).all()

        t_levels = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
        t_total = 0.0
        for tx in t_txs:
            cat = tx.category or "其他"
            level = _get_level(cat)
            t_levels[level] += tx.amount
            t_total += tx.amount

        trend.append({
            "year": ty,
            "month": tm,
            "total": round(t_total, 2),
            "l1_amount": round(t_levels["L1"], 2),
            "l2_amount": round(t_levels["L2"], 2),
            "l3_amount": round(t_levels["L3"], 2),
            "l1_pct": round(t_levels["L1"] / t_total * 100, 1) if t_total > 0 else 0,
            "l2_pct": round(t_levels["L2"] / t_total * 100, 1) if t_total > 0 else 0,
            "l3_pct": round(t_levels["L3"] / t_total * 100, 1) if t_total > 0 else 0,
        })

    # --- 环比分析 ---
    mom_change = None
    if len(trend) >= 2:
        curr = trend[-1]
        prev = trend[-2]
        if prev["total"] > 0:
            mom_change = {
                "total_change": round(curr["total"] - prev["total"], 2),
                "total_change_pct": round((curr["total"] - prev["total"]) / prev["total"] * 100, 1),
                "l1_change_pct": round(curr["l1_pct"] - prev["l1_pct"], 1),
                "l2_change_pct": round(curr["l2_pct"] - prev["l2_pct"], 1),
                "l3_change_pct": round(curr["l3_pct"] - prev["l3_pct"], 1),
            }

    # --- Top 支出分类（跨级别）---
    top_categories = sorted(cat_amounts.items(), key=lambda x: -x[1])[:10]
    top_categories = [
        {
            "category": cat,
            "amount": round(amt, 2),
            "percentage": round(amt / total_expense * 100, 1) if total_expense > 0 else 0,
            "level": _get_level(cat),
            "level_label": LEVEL_LABELS.get(_get_level(cat), "改善支出"),
        }
        for cat, amt in top_categories
    ]

    return {
        "year": y,
        "month": m,
        "summary": {
            "total_expense": round(total_expense, 2),
            "l1_amount": round(level_amounts["L1"], 2),
            "l1_pct": round(level_amounts["L1"] / total_expense * 100, 1) if total_expense > 0 else 0,
            "l2_amount": round(level_amounts["L2"], 2),
            "l2_pct": round(level_amounts["L2"] / total_expense * 100, 1) if total_expense > 0 else 0,
            "l3_amount": round(level_amounts["L3"], 2),
            "l3_pct": round(level_amounts["L3"] / total_expense * 100, 1) if total_expense > 0 else 0,
            "category_count": len(cat_amounts),
            "transaction_count": len(month_txs),
        },
        "by_level": by_level,
        "structure_health": structure_health,
        "trend": trend,
        "mom_change": mom_change,
        "top_categories": top_categories,
    }


# ===== 财务健康评分（V2-016 五维度评分模型）=====

# 必要支出分类（用于支出结构维度）


NECESSARY_CATEGORIES = {
    "房租", "房贷", "水电", "燃气", "物业", "餐饮", "食品", " groceries",
    "交通", "地铁", "公交", "医疗", "药品", "保险", "通讯", "话费",
    "宽带", "教育", "学费", "日用", "日用品", "服饰", "基本",
}
# 非必要支出分类
DISCRETIONARY_CATEGORIES = {
    "娱乐", "游戏", "电影", "旅游", "奢侈品", "奢侈品", "酒吧",
    "KTV", "健身", "美容", "美甲", "SPA", "数码", "电子产品",
}


def _score_savings(total_income: float, total_expense: float) -> dict:
    """💰 储蓄能力（25分）：月储蓄率"""
    if total_income <= 0:
        return {
            "score": 0, "max": 25, "rate": 0,
            "message": "无收入数据，请添加收入记录",
            "suggestion": "先记录至少一个月的完整收支数据",
        }
    rate = (total_income - total_expense) / total_income * 100
    if rate >= 30:
        score = 25
    elif rate >= 20:
        score = 20
    elif rate >= 10:
        score = 15
    elif rate >= 0:
        score = 8
    else:
        score = 0

    suggestions = []
    if rate < 10:
        suggestions.append("储蓄率偏低，建议从减少非必要支出开始")
    if rate < 0:
        suggestions.append("当前入不敷出，需要紧急调整消费结构")
    if rate >= 30:
        msg = f"储蓄率 {rate:.1f}%，优秀！"
    elif rate >= 20:
        msg = f"储蓄率 {rate:.1f}%，良好"
    elif rate >= 10:
        msg = f"储蓄率 {rate:.1f}%，还有提升空间"
    elif rate >= 0:
        msg = f"储蓄率 {rate:.1f}%，偏低"
    else:
        msg = f"储蓄率 {rate:.1f}%，入不敷出"

    return {
        "score": score, "max": 25, "rate": round(rate, 1),
        "message": msg,
        "suggestion": suggestions[0] if suggestions else "继续保持当前储蓄水平",
    }


def _score_risk(emergency_balance: float, monthly_expense: float) -> dict:
    """🛡️ 抗风险能力（25分）：应急储备覆盖月数"""
    if monthly_expense <= 0:
        months = 0
    else:
        months = emergency_balance / monthly_expense

    if months >= 6:
        score = 25
    elif months >= 3:
        score = 20
    elif months >= 1:
        score = 12
    elif months > 0:
        score = 5
    else:
        score = 0

    if months >= 6:
        msg = f"应急储备可覆盖 {months:.1f} 个月，充足"
    elif months >= 3:
        msg = f"应急储备可覆盖 {months:.1f} 个月，良好"
    elif months >= 1:
        msg = f"应急储备可覆盖 {months:.1f} 个月，建议补充到 3-6 个月"
    elif months > 0:
        msg = f"应急储备仅覆盖 {months:.1f} 个月，不足"
    else:
        msg = "无应急储备数据"

    return {
        "score": score, "max": 25, "months": round(months, 1),
        "message": msg,
        "suggestion": "将应急账户储备到覆盖 3-6 个月生活费" if months < 3 else "应急储备充足，可考虑多余部分用于投资",
    }


def _score_budget(budget_execution: list) -> dict:
    """📊 预算纪律（20分）：预算执行率"""
    if not budget_execution:
        return {
            "score": 0, "max": 20, "execution_rate": 0,
            "message": "未设置预算",
            "suggestion": "先使用预算模板创建分类预算，再评估执行纪律",
        }

    # 执行率 = 100% - 平均偏差率（超支扣分，节约不加分过多）
    deviations = []
    for b in budget_execution:
        usage = b.get("usage_rate", 0) / 100  # 0~1+
        if usage > 1:
            deviations.append(usage - 1)  # 超支部分
        else:
            deviations.append(0)  # 节约不视为偏差

    avg_deviation = sum(deviations) / len(deviations) if deviations else 0
    execution_rate = max(0, 100 - avg_deviation * 100)

    if execution_rate >= 90:
        score = 20
    elif execution_rate >= 80:
        score = 15
    elif execution_rate >= 70:
        score = 10
    elif execution_rate >= 60:
        score = 5
    else:
        score = 0

    if execution_rate >= 90:
        msg = f"预算执行率 {execution_rate:.0f}%，纪律优秀"
    elif execution_rate >= 80:
        msg = f"预算执行率 {execution_rate:.0f}%，良好"
    elif execution_rate >= 70:
        msg = f"预算执行率 {execution_rate:.0f}%，有超支倾向"
    elif execution_rate >= 60:
        msg = f"预算执行率 {execution_rate:.0f}%，需加强控制"
    else:
        msg = f"预算执行率 {execution_rate:.0f}%，严重超支"

    return {
        "score": score, "max": 20, "execution_rate": round(execution_rate, 1),
        "message": msg,
        "suggestion": "控制超支分类，必要时调整预算额度" if execution_rate < 80 else "预算纪律良好，继续保持",
    }


def _score_expense_structure(transactions: list) -> dict:
    """🏗️ 支出结构（15分）：必要支出占比"""
    expenses = [t for t in transactions if t.transaction_type == "expense"]
    if not expenses:
        return {
            "score": 0, "max": 15, "necessary_ratio": 0,
            "message": "无支出数据",
            "suggestion": "先记录日常支出数据",
        }

    total = sum(t.amount for t in expenses)
    necessary = sum(t.amount for t in expenses if t.category in NECESSARY_CATEGORIES)
    ratio = necessary / total * 100 if total > 0 else 0

    if ratio < 50:
        score = 15
    elif ratio < 60:
        score = 12
    elif ratio < 70:
        score = 8
    elif ratio < 80:
        score = 4
    else:
        score = 0

    if ratio < 50:
        msg = f"必要支出占比 {ratio:.0f}%，结构健康"
    elif ratio < 60:
        msg = f"必要支出占比 {ratio:.0f}%，结构良好"
    elif ratio < 70:
        msg = f"必要支出占比 {ratio:.0f}%，偏高"
    elif ratio < 80:
        msg = f"必要支出占比 {ratio:.0f}%，必要支出占比过高"
    else:
        msg = f"必要支出占比 {ratio:.0f}%，结构紧张"

    return {
        "score": score, "max": 15, "necessary_ratio": round(ratio, 1),
        "message": msg,
        "suggestion": "尝试降低非必要支出比例" if ratio >= 60 else "支出结构合理，继续保持",
    }


def _score_investment_growth(db: Session) -> dict:
    """📈 投资增长（15分）：投资类资产月度变化"""
    # 查询投资类账户和资产的当前值
    investment_accounts = db.query(Account).filter(
        Account.purpose == "investment",
        Account.status == "active"
    ).all()
    investment_assets = db.query(Asset).filter(
        Asset.asset_type.in_(["fund", "stock", "bond"]),
        Asset.status == "active"
    ).all()

    current_value = sum(a.balance for a in investment_accounts) + sum(a.current_value for a in investment_assets)

    if current_value <= 0:
        return {
            "score": 0, "max": 15, "growth_rate": 0,
            "message": "无投资数据",
            "suggestion": "建立投资账户并记录投资资产，开始理财规划",
        }

    # 尝试获取上月数据（通过交易记录中的投资类支出反推）
    now = datetime.utcnow()
    this_month_start = datetime(now.year, now.month, 1)
    last_month_start = this_month_start - timedelta(days=30)

    # 简化：用当月投资类资产变化估算增长率
    # 如果有初始值，用 (current - initial) / initial
    initial_total = sum(a.initial_value for a in investment_assets)
    if initial_total > 0:
        growth_rate = (current_value - initial_total) / initial_total * 100
    else:
        # 无初始值数据，给中间分
        return {
            "score": 8, "max": 15, "growth_rate": None,
            "current_value": round(current_value, 2),
            "message": f"投资资产 {current_value:.0f} 元，缺少历史对比数据",
            "suggestion": "为投资资产设置初始值，以便追踪增长",
        }

    if growth_rate >= 5:
        score = 15
    elif growth_rate >= 2:
        score = 12
    elif growth_rate >= 0:
        score = 8
    elif growth_rate >= -2:
        score = 4
    else:
        score = 0

    if growth_rate >= 5:
        msg = f"投资增长 {growth_rate:.1f}%，表现优秀"
    elif growth_rate >= 2:
        msg = f"投资增长 {growth_rate:.1f}%，表现良好"
    elif growth_rate >= 0:
        msg = f"投资增长 {growth_rate:.1f}%，增长缓慢"
    elif growth_rate >= -2:
        msg = f"投资变化 {growth_rate:.1f}%，略有下降"
    else:
        msg = f"投资变化 {growth_rate:.1f}%，需关注"

    return {
        "score": score, "max": 15, "growth_rate": round(growth_rate, 1),
        "current_value": round(current_value, 2),
        "message": msg,
        "suggestion": "保持当前投资策略" if growth_rate >= 2 else "审视投资组合，考虑分散风险",
    }


@router.get("/reports/health-score")
async def get_health_score(year: int = None, month: int = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """
    财务健康评分（五维度模型，满分100分）

    维度：
    - 💰 储蓄能力（25分）：月储蓄率
    - 🛡️ 抗风险能力（25分）：应急储备覆盖月数
    - 📊 预算纪律（20分）：预算执行率
    - 🏗️ 支出结构（15分）：必要支出占比
    - 📈 投资增长（15分）：投资资产增长率

    等级：
    - 90-100：🏆 财务优秀
    - 75-89：✅ 财务健康
    - 60-74：⚠️ 财务一般
    - 40-59：🔶 财务紧张
    - 0-39：🔴 财务危险
    """
    import json as _json

    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month

    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)

    # 本月交易
    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= start,
        Transaction.parsed_at < end
    ).all()

    total_income = sum(t.amount for t in transactions if t.transaction_type == "income")
    total_expense = sum(t.amount for t in transactions if t.transaction_type == "expense")

    # 应急账户余额
    emergency_accounts = db.query(Account).filter(
        Account.purpose == "emergency",
        Account.status == "active"
    ).all()
    emergency_balance = sum(a.balance for a in emergency_accounts)

    # 预算执行数据
    raw_budgets = db.query(Setting).filter(Setting.key == "budgets").first()
    budgets = _json.loads(raw_budgets.value) if raw_budgets and raw_budgets.value else []
    budget_execution = []
    for b in budgets:
        spent = sum(t.amount for t in transactions if t.category == b["category"] and t.transaction_type == "expense")
        limit = b["monthly_limit"]
        usage = spent / limit * 100 if limit > 0 else 0
        budget_execution.append({
            "category": b["category"],
            "budget_limit": round(limit, 2),
            "actual_spent": round(spent, 2),
            "usage_rate": round(usage, 1),
        })

    # 五维度评分
    dim_savings = _score_savings(total_income, total_expense)
    dim_risk = _score_risk(emergency_balance, total_expense)
    dim_budget = _score_budget(budget_execution)
    dim_structure = _score_expense_structure(transactions)
    dim_investment = _score_investment_growth(db)

    total_score = dim_savings["score"] + dim_risk["score"] + dim_budget["score"] + dim_structure["score"] + dim_investment["score"]

    # 等级判定
    if total_score >= 90:
        grade = "🏆 财务优秀"
        grade_code = "excellent"
    elif total_score >= 75:
        grade = "✅ 财务健康"
        grade_code = "healthy"
    elif total_score >= 60:
        grade = "⚠️ 财务一般"
        grade_code = "average"
    elif total_score >= 40:
        grade = "🔶 财务紧张"
        grade_code = "tight"
    else:
        grade = "🔴 财务危险"
        grade_code = "danger"

    # 雷达图数据（归一化到 0-1）
    radar = {
        "savings": dim_savings["score"] / dim_savings["max"],
        "risk": dim_risk["score"] / dim_risk["max"],
        "budget": dim_budget["score"] / dim_budget["max"],
        "structure": dim_structure["score"] / dim_structure["max"],
        "investment": dim_investment["score"] / dim_investment["max"],
    }

    # 综合建议（取最低分维度的建议）
    dimensions = [
        ("储蓄能力", dim_savings),
        ("抗风险能力", dim_risk),
        ("预算纪律", dim_budget),
        ("支出结构", dim_structure),
        ("投资增长", dim_investment),
    ]
    weakest = min(dimensions, key=lambda x: x[1]["score"] / x[1]["max"])
    top_suggestion = f"最需要改善「{weakest[0]}」：{weakest[1]['suggestion']}"

    return {
        "year": y,
        "month": m,
        "period": f"{y}年{m}月",
        "total_score": total_score,
        "max_score": 100,
        "grade": grade,
        "grade_code": grade_code,
        "dimensions": {
            "savings": dim_savings,
            "risk": dim_risk,
            "budget": dim_budget,
            "structure": dim_structure,
            "investment": dim_investment,
        },
        "radar": radar,
        "top_suggestion": top_suggestion,
        "data_sources": {
            "transaction_count": len(transactions),
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "emergency_balance": round(emergency_balance, 2),
            "budget_count": len(budgets),
        },
    }


# ===== 风险画像推断（V2-017）=====
