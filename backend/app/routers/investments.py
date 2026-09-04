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

@router.get("/investment/risk-profile")
async def get_risk_profile(year: int = None, month: int = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """
    基于消费习惯推断投资风险承受能力

    推断逻辑：
    - 消费稳定（月度变异系数低）+ 应急充足 → 稳健型
    - 消费波动大 + 应急不足 → 保守型
    - 消费克制 + 应急充足 + 有投资经验 → 激进型

    输出：风险等级/风险分数/投资期限/流动性需求/配置建议
    """
    import json as _json
    import math

    now = datetime.utcnow()
    y = year or now.year
    m = month or now.month

    # 取最近 6 个月交易数据
    end = datetime(y, m + 1, 1) if m < 12 else datetime(y + 1, 1, 1)
    start = end - timedelta(days=180)  # 约 6 个月

    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= start,
        Transaction.parsed_at < end,
    ).all()

    # 按月聚合支出
    monthly_expenses = {}
    for t in transactions:
        if t.transaction_type != "expense":
            continue
        key = (t.parsed_at.year, t.parsed_at.month)
        monthly_expenses[key] = monthly_expenses.get(key, 0) + t.amount

    expenses_list = list(monthly_expenses.values()) if monthly_expenses else []
    n_months = len(expenses_list)

    # --- 维度1：消费稳定性（变异系数 CV = std/mean）---
    if n_months >= 2 and sum(expenses_list) > 0:
        mean_exp = sum(expenses_list) / n_months
        variance = sum((x - mean_exp) ** 2 for x in expenses_list) / n_months
        std_exp = math.sqrt(variance)
        cv = std_exp / mean_exp if mean_exp > 0 else 1
        # CV < 0.2 稳定, 0.2-0.5 中等, > 0.5 波动大
        if cv < 0.2:
            stability_score = 3
            stability_msg = "消费非常稳定"
        elif cv < 0.5:
            stability_score = 2
            stability_msg = "消费较稳定"
        elif cv < 0.8:
            stability_score = 1
            stability_msg = "消费波动较大"
        else:
            stability_score = 0
            stability_msg = "消费波动极大"
    else:
        cv = None
        stability_score = 1  # 数据不足，默认中等
        stability_msg = "数据不足，默认中等"

    # --- 维度2：应急充足度 ---
    avg_monthly_exp = sum(expenses_list) / n_months if n_months > 0 else 0
    emergency_accounts = db.query(Account).filter(
        Account.purpose == "emergency",
        Account.status == "active"
    ).all()
    emergency_balance = sum(a.balance for a in emergency_accounts)
    coverage_months = emergency_balance / avg_monthly_exp if avg_monthly_exp > 0 else 0

    if coverage_months >= 6:
        emergency_score = 3
        emergency_msg = "应急储备充足（≥6个月）"
    elif coverage_months >= 3:
        emergency_score = 2
        emergency_msg = "应急储备良好（3-6个月）"
    elif coverage_months >= 1:
        emergency_score = 1
        emergency_msg = "应急储备不足（1-3个月）"
    else:
        emergency_score = 0
        emergency_msg = "无应急储备"

    # --- 维度3：消费克制力（储蓄率）---
    total_income = sum(t.amount for t in transactions if t.transaction_type == "income")
    total_expense = sum(t.amount for t in transactions if t.transaction_type == "expense")
    savings_rate = (total_income - total_expense) / total_income if total_income > 0 else 0

    if savings_rate >= 0.3:
        discipline_score = 3
        discipline_msg = "消费克制，储蓄率高"
    elif savings_rate >= 0.15:
        discipline_score = 2
        discipline_msg = "消费较克制"
    elif savings_rate >= 0:
        discipline_score = 1
        discipline_msg = "储蓄率偏低"
    else:
        discipline_score = 0
        discipline_msg = "入不敷出"

    # --- 维度4：投资经验 ---
    investment_accounts = db.query(Account).filter(
        Account.purpose == "investment",
        Account.status == "active"
    ).all()
    investment_assets = db.query(Asset).filter(
        Asset.asset_type.in_(["fund", "stock", "bond"]),
        Asset.status == "active"
    ).all()
    investment_value = sum(a.balance for a in investment_accounts) + sum(a.current_value for a in investment_assets)

    if investment_value > 50000:
        experience_score = 3
        experience_msg = "有丰富投资经验"
    elif investment_value > 10000:
        experience_score = 2
        experience_msg = "有一定投资经验"
    elif investment_value > 0:
        experience_score = 1
        experience_msg = "有少量投资经验"
    else:
        experience_score = 0
        experience_msg = "无投资经验"

    # --- 综合评分（满分12分）---
    raw_score = stability_score + emergency_score + discipline_score + experience_score
    # 归一化到 0-100
    risk_score = round(raw_score / 12 * 100)

    # --- 风险等级判定 ---
    # 激进型：高纪律 + 高应急 + 有投资经验
    if discipline_score >= 2 and emergency_score >= 2 and experience_score >= 2:
        risk_level = "aggressive"
        risk_label = "激进型"
        risk_emoji = "🔥"
        investment_horizon = "5年以上"
        liquidity_need = "低（可长期锁定）"
        allocation = {"fixed_income": 30, "mixed": 30, "equity": 40}
        description = "消费自律、储备充足、有投资经验，可承受较高波动追求长期高收益"
    # 稳健型：应急充足 + 消费稳定
    elif emergency_score >= 2 and stability_score >= 2:
        risk_level = "balanced"
        risk_label = "稳健型"
        risk_emoji = "⚖️"
        investment_horizon = "3-5年"
        liquidity_need = "中（保留部分灵活资金）"
        allocation = {"fixed_income": 50, "mixed": 30, "equity": 20}
        description = "消费稳定、有一定储备，适合平衡风险与收益"
    # 保守型：应急不足 + 消费波动
    elif emergency_score <= 1 or stability_score <= 1:
        risk_level = "conservative"
        risk_label = "保守型"
        risk_emoji = "🛡️"
        investment_horizon = "1-3年"
        liquidity_need = "高（需保持流动性）"
        allocation = {"fixed_income": 70, "mixed": 20, "equity": 10}
        description = "应急储备不足或消费波动大，应优先保障流动性，谨慎投资"
    # 默认：谨慎型
    else:
        risk_level = "cautious"
        risk_label = "谨慎型"
        risk_emoji = "🔍"
        investment_horizon = "1-3年"
        liquidity_need = "中高（逐步建立应急储备）"
        allocation = {"fixed_income": 60, "mixed": 25, "equity": 15}
        description = "财务状况中等，建议先完善应急储备再逐步增加投资"

    # --- 优先行动建议 ---
    actions = []
    if emergency_score < 2:
        actions.append("优先补充应急储备到 3-6 个月生活费")
    if stability_score < 2:
        actions.append("建立预算控制消费波动")
    if discipline_score < 2:
        actions.append("提高储蓄率，目标 ≥ 20%")
    if experience_score < 2:
        actions.append("从货币基金或指数基金开始积累投资经验")
    if not actions:
        actions.append("当前财务状况良好，可按计划执行投资策略")

    return {
        "as_of": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "risk_level": risk_level,
        "risk_label": risk_label,
        "risk_emoji": risk_emoji,
        "risk_score": risk_score,
        "investment_horizon": investment_horizon,
        "liquidity_need": liquidity_need,
        "description": description,
        "allocation_suggestion": allocation,
        "dimensions": {
            "stability": {"score": stability_score, "max": 3, "message": stability_msg, "cv": round(cv, 2) if cv is not None else None},
            "emergency": {"score": emergency_score, "max": 3, "message": emergency_msg, "coverage_months": round(coverage_months, 1)},
            "discipline": {"score": discipline_score, "max": 3, "message": discipline_msg, "savings_rate": round(savings_rate * 100, 1)},
            "experience": {"score": experience_score, "max": 3, "message": experience_msg, "investment_value": round(investment_value, 2)},
        },
        "action_items": actions,
        "data_sources": {
            "months_analyzed": n_months,
            "total_transactions": len(transactions),
            "avg_monthly_expense": round(avg_monthly_exp, 2),
        },
    }


# ===== 资产配置建议（V2-018）=====

# 风险等级对应的目标配置


ALLOCATION_TARGETS = {
    "aggressive": {"fixed_income": 30, "mixed": 30, "equity": 40},
    "balanced": {"fixed_income": 50, "mixed": 30, "equity": 20},
    "cautious": {"fixed_income": 60, "mixed": 25, "equity": 15},
    "conservative": {"fixed_income": 70, "mixed": 20, "equity": 10},
}

# 资产类型到配置类别的映射
ASSET_TO_ALLOCATION = {
    "cash": "fixed_income",
    "savings": "fixed_income",
    "bond": "fixed_income",
    "fund": "mixed",
    "stock": "equity",
    "property": "equity",
    "other": "mixed",
}


@router.get("/investment/allocation")
async def get_asset_allocation(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """
    资产配置建议 + 实际配置追踪 + 再平衡提醒

    功能：
    1. 基于风险画像给出目标配置
    2. 计算当前实际配置比例
    3. 偏离度 > 5% 时发出再平衡提醒
    """
    # --- 1. 获取风险等级（简化版，复用逻辑）---
    # 投资账户和资产
    investment_accounts = db.query(Account).filter(
        Account.purpose == "investment",
        Account.status == "active"
    ).all()
    investment_assets = db.query(Asset).filter(
        Asset.asset_type.in_(["fund", "stock", "bond", "cash", "savings"]),
        Asset.status == "active"
    ).all()

    # 计算当前配置
    allocation_map = {"fixed_income": 0, "mixed": 0, "equity": 0}

    # 账户按类型归类
    for acc in investment_accounts:
        # 投资账户默认归入 mixed
        allocation_map["mixed"] += acc.balance

    # 资产按类型归类
    for asset in investment_assets:
        category = ASSET_TO_ALLOCATION.get(asset.asset_type, "mixed")
        allocation_map[category] += asset.current_value

    total_investment = sum(allocation_map.values())

    if total_investment <= 0:
        # 无投资数据，返回建议配置
        return {
            "has_investment": False,
            "message": "暂无投资数据，请先建立投资账户和记录投资资产",
            "suggested_allocation": ALLOCATION_TARGETS["balanced"],  # 默认稳健型
            "current_allocation": {},
            "deviation": {},
            "rebalance_alerts": [],
        }

    # --- 2. 计算实际比例 ---
    current_pct = {
        k: round(v / total_investment * 100, 1)
        for k, v in allocation_map.items()
    }

    # --- 3. 确定风险等级（简化判断）---
    emergency_accounts = db.query(Account).filter(
        Account.purpose == "emergency",
        Account.status == "active"
    ).all()
    emergency_balance = sum(a.balance for a in emergency_accounts)

    # 简单判断：有投资+有应急 → balanced，否则 conservative
    if emergency_balance > 0 and len(investment_assets) >= 2:
        risk_level = "balanced"
    elif emergency_balance > 0:
        risk_level = "cautious"
    else:
        risk_level = "conservative"

    target = ALLOCATION_TARGETS[risk_level]

    # --- 4. 计算偏离度 ---
    deviation = {}
    rebalance_alerts = []
    for category in ["fixed_income", "mixed", "equity"]:
        actual = current_pct.get(category, 0)
        target_pct = target[category]
        diff = actual - target_pct
        deviation[category] = round(diff, 1)

        if abs(diff) > 5:
            direction = "超配" if diff > 0 else "低配"
            cat_labels = {"fixed_income": "固收类", "mixed": "混合类", "equity": "权益类"}
            cat_label = cat_labels[category]
            rebalance_alerts.append({
                "category": category,
                "category_label": cat_label,
                "target_pct": target_pct,
                "actual_pct": actual,
                "deviation": round(diff, 1),
                "direction": direction,
                "action": f"建议{direction}{cat_label} {abs(round(diff, 0))}%",
            })

    category_labels = {
        "fixed_income": "固收类（现金/存款/债券）",
        "mixed": "混合类（基金/理财）",
        "equity": "权益类（股票/房产）",
    }

    return {
        "has_investment": True,
        "risk_level": risk_level,
        "total_investment": round(total_investment, 2),
        "target_allocation": {
            k: {"pct": v, "label": category_labels[k]}
            for k, v in target.items()
        },
        "current_allocation": {
            k: {"pct": current_pct.get(k, 0), "amount": round(allocation_map[k], 2), "label": category_labels[k]}
            for k in ["fixed_income", "mixed", "equity"]
        },
        "deviation": deviation,
        "rebalance_alerts": rebalance_alerts,
        "needs_rebalance": len(rebalance_alerts) > 0,
        "suggestion": _get_allocation_suggestion(risk_level, deviation),
    }


def _get_allocation_suggestion(risk_level: str, deviation: dict) -> str:
    """根据风险等级和偏离度给出建议"""
    if not any(abs(v) > 5 for v in deviation.values()):
        return "当前资产配置与目标基本一致，继续保持"

    suggestions = []
    if deviation.get("equity", 0) > 5:
        suggestions.append("权益类超配，可适当减仓锁定收益")
    elif deviation.get("equity", 0) < -5:
        suggestions.append("权益类低配，可逐步增配提升长期收益")

    if deviation.get("fixed_income", 0) > 5:
        suggestions.append("固收类超配，收益偏低，可考虑部分转投混合类")
    elif deviation.get("fixed_income", 0) < -5:
        suggestions.append("固收类低配，建议补充货币基金或债券作为安全垫")

    return "；".join(suggestions) if suggestions else "当前配置合理"


# ===== 持仓管理（V2-019）=====

from ..database import Position, TradeRecord
from pydantic import BaseModel as _BaseModel


class PositionCreate(_BaseModel):
    name: str
    symbol: Optional[str] = None
    position_type: str = "fund"  # stock/fund/bond/wealth_mgmt/other
    quantity: float = 0
    avg_cost: float = 0
    current_price: float = 0
    currency: str = "CNY"
    account: Optional[str] = None
    notes: Optional[str] = None


class PositionUpdate(_BaseModel):
    name: Optional[str] = None
    symbol: Optional[str] = None
    position_type: Optional[str] = None
    quantity: Optional[float] = None
    avg_cost: Optional[float] = None
    current_price: Optional[float] = None
    account: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class TradeRecordCreate(_BaseModel):
    position_id: int
    trade_type: str  # buy/sell/dividend
    quantity: float
    price: float
    trade_date: str  # YYYY-MM-DD
    fee: float = 0
    notes: Optional[str] = None


@router.get("/positions")
async def list_positions(status: str = "active", user: User = Depends(require_user), db: Session = Depends(get_db)):
    """持仓列表"""
    query = db.query(Position)
    if status:
        query = query.filter(Position.status == status)
    positions = query.all()

    result = []
    for p in positions:
        market_value = p.quantity * p.current_price
        cost_value = p.quantity * p.avg_cost
        profit = market_value - cost_value
        profit_pct = profit / cost_value * 100 if cost_value > 0 else 0
        result.append({
            "id": p.id,
            "name": p.name,
            "symbol": p.symbol,
            "position_type": p.position_type,
            "quantity": p.quantity,
            "avg_cost": round(p.avg_cost, 4),
            "current_price": round(p.current_price, 4),
            "market_value": round(market_value, 2),
            "cost_value": round(cost_value, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "account": p.account,
            "status": p.status,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        })

    total_value = sum(r["market_value"] for r in result)
    total_cost = sum(r["cost_value"] for r in result)
    total_profit = total_value - total_cost
    total_profit_pct = total_profit / total_cost * 100 if total_cost > 0 else 0

    return {
        "positions": result,
        "summary": {
            "count": len(result),
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_profit, 2),
            "total_profit_pct": round(total_profit_pct, 2),
        }
    }


@router.post("/positions")
async def create_position(pos: PositionCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """创建持仓，同时同步到资产表"""
    position = Position(
        name=pos.name,
        symbol=pos.symbol,
        position_type=pos.position_type,
        quantity=pos.quantity,
        avg_cost=pos.avg_cost,
        current_price=pos.current_price,
        account=pos.account,
        notes=pos.notes,
    )
    db.add(position)
    db.flush()
    
    # 同步到资产表
    market_value = pos.quantity * pos.current_price
    asset_type_map = {
        "stock": "stock", "fund": "fund", "bond": "bond",
        "wealth_mgmt": "other", "other": "other",
    }
    asset = Asset(
        name=f"[持仓] {pos.name}",
        asset_type=asset_type_map.get(pos.position_type, "other"),
        account=pos.account or "",
        current_value=market_value,
        initial_value=pos.quantity * pos.avg_cost,
        currency=pos.currency,
        liquidity="low" if pos.position_type in ["stock", "fund"] else "medium",
        status="active",
        notes=f"关联持仓ID={position.id}, 代码={pos.symbol or 'N/A'}",
    )
    db.add(asset)
    
    db.commit()
    db.refresh(position)
    return {"id": position.id, "name": position.name, "asset_id": asset.id, "message": "持仓创建成功，已同步到资产表"}


@router.put("/positions/{position_id}")
async def update_position(position_id: int, pos: PositionUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """更新持仓（修改当前价格等），同时同步资产表"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="持仓不存在")

    for field, value in pos.model_dump(exclude_unset=True).items():
        setattr(position, field, value)
    position.updated_at = datetime.utcnow()
    
    # 同步更新资产表中的对应条目（通过持仓ID精确匹配，避免同名持仓冲突）
    market_value = position.quantity * position.current_price
    linked_asset = db.query(Asset).filter(
        Asset.notes == f"关联持仓ID={position.id}, 代码={position.symbol or 'N/A'}",
        Asset.status == "active"
    ).first()
    if not linked_asset:
        # fallback: 按名称匹配（兼容旧数据）
        linked_asset = db.query(Asset).filter(
            Asset.name == f"[持仓] {position.name}",
            Asset.status == "active"
        ).first()
    if linked_asset:
        linked_asset.current_value = market_value
        linked_asset.updated_at = datetime.utcnow()
    
    db.commit()
    return {"message": "持仓更新成功，资产已同步", "id": position_id}


@router.delete("/positions/{position_id}")
async def close_position(position_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """关闭持仓（标记为 closed），同时关闭资产表中的对应条目"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="持仓不存在")
    position.status = "closed"
    position.updated_at = datetime.utcnow()
    
    # 同步关闭资产表中的对应条目（通过持仓ID精确匹配）
    linked_asset = db.query(Asset).filter(
        Asset.notes == f"关联持仓ID={position.id}, 代码={position.symbol or 'N/A'}",
        Asset.status == "active"
    ).first()
    if not linked_asset:
        # fallback: 按名称匹配（兼容旧数据）
        linked_asset = db.query(Asset).filter(
            Asset.name == f"[持仓] {position.name}",
            Asset.status == "active"
        ).first()
    if linked_asset:
        linked_asset.status = "closed"
        linked_asset.updated_at = datetime.utcnow()
    
    db.commit()
    return {"message": "持仓已关闭，资产已同步", "id": position_id}


@router.post("/positions/trades")
async def add_trade(trade: TradeRecordCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """记录买入/卖出交易，自动更新持仓"""
    position = db.query(Position).filter(Position.id == trade.position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="持仓不存在")

    amount = trade.quantity * trade.price
    trade_date = datetime.strptime(trade.trade_date, "%Y-%m-%d").date()

    record = TradeRecord(
        position_id=trade.position_id,
        trade_type=trade.trade_type,
        quantity=trade.quantity,
        price=trade.price,
        amount=amount,
        fee=trade.fee,
        trade_date=trade_date,
        notes=trade.notes,
    )
    db.add(record)

    # 更新持仓
    if trade.trade_type == "buy":
        # 买入：增加数量，重算平均成本
        total_cost = position.quantity * position.avg_cost + amount + trade.fee
        position.quantity += trade.quantity
        position.avg_cost = total_cost / position.quantity if position.quantity > 0 else 0
    elif trade.trade_type == "sell":
        # 卖出：减少数量
        if trade.quantity > position.quantity:
            raise HTTPException(status_code=400, detail="卖出数量超过持有数量")
        position.quantity -= trade.quantity
        if position.quantity <= 0:
            position.status = "closed"

    position.updated_at = datetime.utcnow()
    
    # 同步更新资产表（通过持仓ID精确匹配）
    market_value = position.quantity * position.current_price
    linked_asset = db.query(Asset).filter(
        Asset.notes == f"关联持仓ID={position.id}, 代码={position.symbol or 'N/A'}",
    ).first()
    if not linked_asset:
        linked_asset = db.query(Asset).filter(
            Asset.name == f"[持仓] {position.name}",
        ).first()
    if linked_asset:
        if position.quantity <= 0:
            linked_asset.status = "closed"
        else:
            linked_asset.current_value = market_value
            linked_asset.initial_value = position.quantity * position.avg_cost
        linked_asset.updated_at = datetime.utcnow()
    
    db.commit()

    return {
        "message": f"交易记录已添加（{trade.trade_type}）",
        "position_id": trade.position_id,
        "remaining_quantity": position.quantity,
    }


@router.get("/positions/{position_id}/trades")
async def get_position_trades(position_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取持仓的交易历史"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="持仓不存在")

    trades = db.query(TradeRecord).filter(
        TradeRecord.position_id == position_id
    ).order_by(TradeRecord.trade_date.desc()).all()

    return {
        "position_id": position_id,
        "position_name": position.name,
        "trades": [
            {
                "id": t.id,
                "trade_type": t.trade_type,
                "quantity": t.quantity,
                "price": t.price,
                "amount": round(t.amount, 2),
                "fee": t.fee,
                "trade_date": t.trade_date.isoformat(),
                "notes": t.notes,
            }
            for t in trades
        ],
        "total_trades": len(trades),
    }


# ===== 资产同步 =====
from ..database import SyncLog
from ..asset_sync import sync_all_positions


@router.post("/sync/assets")
async def trigger_asset_sync(
    sync_type: str = "manual",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """手动触发资产同步"""
    # 创建同步日志
    log = SyncLog(sync_type=sync_type, status="running")
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        result = await sync_all_positions(db)
        log.status = "completed"
        log.total_count = result.get("total", 0)
        log.updated_count = result.get("updated", 0)
        log.failed_count = result.get("failed", 0)
        log.skipped_count = result.get("skipped", 0)
        log.details = json.dumps(result.get("details", []), ensure_ascii=False)
        log.completed_at = datetime.utcnow()
        db.commit()
        return {"message": "同步完成", "log_id": log.id, **result}
    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)
        log.completed_at = datetime.utcnow()
        db.commit()
        return {"message": f"同步失败: {e}", "log_id": log.id, "error": True}


@router.get("/sync/status")
async def get_sync_status(
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """获取最近同步状态"""
    recent = (
        db.query(SyncLog)
        .order_by(SyncLog.started_at.desc())
        .limit(10)
        .all()
    )
    return {
        "recent_syncs": [
            {
                "id": s.id,
                "type": s.sync_type,
                "status": s.status,
                "total": s.total_count,
                "updated": s.updated_count,
                "failed": s.failed_count,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            }
            for s in recent
        ],
        "last_sync": recent[0].started_at.isoformat() if recent else None,
        "last_status": recent[0].status if recent else None,
    }


# ===== 收益追踪（V2-020）=====

import math


def _calc_xirr(cashflows: list, dates: list, guess: float = 0.1) -> float:
    """
    XIRR 计算（牛顿迭代法）
    cashflows: 现金流列表（正数=流入，负数=流出）
    dates: 日期列表（datetime.date）
    返回年化内部收益率
    """
    if len(cashflows) < 2:
        return 0.0

    # 简化牛顿法
    x = guess
    for _ in range(100):
        try:
            d0 = dates[0]
            npv = sum(cf / (1 + x) ** ((d - d0).days / 365.0) for cf, d in zip(cashflows, dates))
            dnpv = sum(-cf * (d - d0).days / 365.0 / (1 + x) ** ((d - d0).days / 365.0 + 1)
                       for cf, d in zip(cashflows, dates))
            if abs(dnpv) < 1e-10:
                break
            x_new = x - npv / dnpv
            if abs(x_new - x) < 1e-6:
                return x_new
            x = x_new
        except (ZeroDivisionError, OverflowError):
            x *= 0.5

    return x if abs(x) < 10 else 0.0


@router.get("/investment/returns")
async def get_investment_returns(position_id: int = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """
    投资收益分析

    返回：
    - 绝对收益率
    - 时间加权收益率（TWR）
    - XIRR（内部收益率）
    - 年化收益率

    支持单持仓或全组合
    """
    if position_id:
        # 单持仓分析
        position = db.query(Position).filter(Position.id == position_id).first()
        if not position:
            raise HTTPException(status_code=404, detail="持仓不存在")

        trades = db.query(TradeRecord).filter(
            TradeRecord.position_id == position_id
        ).order_by(TradeRecord.trade_date.asc()).all()

        if not trades:
            # 无交易记录，用持仓数据直接算
            cost = position.quantity * position.avg_cost
            value = position.quantity * position.current_price
            if cost <= 0:
                return {"position_id": position_id, "message": "无成本数据"}
            abs_return = (value - cost) / cost
            return {
                "position_id": position_id,
                "position_name": position.name,
                "absolute_return": round(abs_return * 100, 2),
                "profit": round(value - cost, 2),
                "cost": round(cost, 2),
                "current_value": round(value, 2),
                "annualized_return": None,
                "xirr": None,
                "message": "无交易记录，仅计算当前盈亏",
            }

        # 有交易记录，计算各种收益率
        return _calc_position_returns(position, trades)

    else:
        # 全组合分析
        positions = db.query(Position).filter(Position.status == "active").all()
        if not positions:
            return {
                "message": "无活跃持仓",
                "total_value": 0,
                "total_cost": 0,
                "absolute_return": 0,
            }

        total_cost = sum(p.quantity * p.avg_cost for p in positions)
        total_value = sum(p.quantity * p.current_price for p in positions)
        abs_return = (total_value - total_cost) / total_cost if total_cost > 0 else 0

        return {
            "portfolio": True,
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "total_profit": round(total_value - total_cost, 2),
            "absolute_return": round(abs_return * 100, 2),
            "position_count": len(positions),
        }


def _calc_position_returns(position, trades):
    """计算单个持仓的各项收益率"""
    # 构建现金流序列
    cashflows = []
    dates = []

    for t in trades:
        if t.trade_type == "buy":
            cashflows.append(-(t.amount + t.fee))  # 买入=现金流出
        elif t.trade_type == "sell":
            cashflows.append(t.amount - t.fee)  # 卖出=现金流入
        elif t.trade_type == "dividend":
            cashflows.append(t.amount)  # 分红=现金流入
        dates.append(t.trade_date)

    # 当前市值作为最终价值（正现金流）
    current_value = position.quantity * position.current_price
    cashflows.append(current_value)
    dates.append(datetime.utcnow().date())

    # 1. 绝对收益率
    total_invested = sum(-cf for cf in cashflows[:-1] if cf < 0)
    total_returned = sum(cf for cf in cashflows[:-1] if cf > 0) + current_value
    abs_return = (total_returned - total_invested) / total_invested if total_invested > 0 else 0

    # 2. 时间加权收益率（简化版：首尾市值法）
    if len(trades) > 0:
        first_trade = trades[0]
        initial_cost = first_trade.amount + first_trade.fee
        # TWR ≈ 最终市值 / 总投入 - 1（简化）
        twr = abs_return  # 简化为绝对收益率
    else:
        twr = 0

    # 3. XIRR
    xirr = _calc_xirr(cashflows, dates)

    # 4. 年化收益率
    if dates:
        days = (dates[-1] - dates[0]).days
        if days > 0:
            annualized = (1 + abs_return) ** (365 / days) - 1
        else:
            annualized = 0
    else:
        annualized = 0
        days = 0

    return {
        "position_id": position.id,
        "position_name": position.name,
        "cost": round(total_invested, 2),
        "current_value": round(current_value, 2),
        "profit": round(total_returned - total_invested, 2),
        "absolute_return": round(abs_return * 100, 2),
        "time_weighted_return": round(twr * 100, 2),
        "xirr": round(xirr * 100, 2) if abs(xirr) < 10 else None,
        "annualized_return": round(annualized * 100, 2),
        "holding_days": days,
        "trade_count": len(trades),
    }

# ==== V2-023 收益率分析（高级组合绩效分析） ====

import math


def _build_daily_portfolio_series(db, days: int):
    """构建每日组合市值序列（用于计算风险指标）
    
    策略：
    1. 获取所有活跃持仓和交易记录
    2. 对每个持仓，根据交易记录推算历史每日持有数量
    3. 用 avg_cost 和 current_price 线性插值估算历史价格
    4. 汇总每日总市值
    """
    positions = db.query(Position).filter(Position.status == "active").all()
    if not positions:
        return []
    
    today = datetime.utcnow().date()
    start_date = today - timedelta(days=days)
    
    # 每个持仓的每日市值贡献
    daily_totals = collections.defaultdict(float)
    
    for pos in positions:
        trades = db.query(TradeRecord).filter(
            TradeRecord.position_id == pos.id
        ).order_by(TradeRecord.trade_date.asc()).all()
        
        if not trades:
            # 无交易记录：假设整个期间持有当前数量
            # 价格用 cost→current 线性插值
            total_days = days
            if total_days <= 0:
                continue
            for d in range(total_days + 1):
                dt = start_date + timedelta(days=d)
                progress = d / total_days
                est_price = pos.avg_cost + (pos.current_price - pos.avg_cost) * progress
                daily_totals[dt] += pos.quantity * est_price
            continue
        
        # 有交易记录：追踪数量变化
        # 构建 (date, cumulative_quantity) 序列
        qty_changes = []
        for t in trades:
            if t.trade_type == "buy":
                qty_changes.append((t.trade_date, t.quantity))
            elif t.trade_type == "sell":
                qty_changes.append((t.trade_date, -t.quantity))
            elif t.trade_type == "dividend":
                pass  # 分红不影响持仓数量
        
        # 估算价格轨迹：从 avg_cost 到 current_price 线性插值
        # 更精确：用交易价格作为锚点
        trade_prices = [(t.trade_date, t.price) for t in trades]
        
        for d in range(days + 1):
            dt = start_date + timedelta(days=d)
            
            # 计算该日的持有数量
            cum_qty = 0
            for td, delta in qty_changes:
                if td <= dt:
                    cum_qty += delta
            
            if cum_qty <= 0:
                continue
            
            # 估算该日价格
            if dt <= trade_prices[0][0]:
                est_price = trade_prices[0][1]
            elif dt >= trade_prices[-1][0]:
                # 最后交易后：线性插值到当前价格
                last_td, last_p = trade_prices[-1]
                days_after = (today - last_td).days
                if days_after > 0:
                    progress = (dt - last_td).days / days_after
                    est_price = last_p + (pos.current_price - last_p) * progress
                else:
                    est_price = pos.current_price
            else:
                # 在交易之间插值
                est_price = trade_prices[0][1]
                for i in range(len(trade_prices) - 1):
                    t0, p0 = trade_prices[i]
                    t1, p1 = trade_prices[i + 1]
                    if t0 <= dt <= t1:
                        span = (t1 - t0).days
                        if span > 0:
                            prog = (dt - t0).days / span
                            est_price = p0 + (p1 - p0) * prog
                        else:
                            est_price = p1
                        break
            
            daily_totals[dt] += cum_qty * est_price
    
    # 转为有序序列
    series = []
    for d in range(days + 1):
        dt = start_date + timedelta(days=d)
        series.append({"date": dt.isoformat(), "value": round(daily_totals.get(dt, 0), 2)})
    
    return series


def _calc_daily_returns(series):
    """从市值序列计算日收益率序列"""
    returns = []
    for i in range(1, len(series)):
        prev = series[i - 1]["value"]
        curr = series[i]["value"]
        if prev > 0:
            r = (curr - prev) / prev
        else:
            r = 0.0
        returns.append(r)
    return returns


def _calc_max_drawdown(series):
    """计算最大回撤"""
    if not series:
        return 0.0
    peak = series[0]["value"]
    max_dd = 0.0
    for point in series:
        val = point["value"]
        if val > peak:
            peak = val
        if peak > 0:
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _calc_volatility(returns, annualize=True):
    """计算波动率（标准差）"""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    vol = variance ** 0.5
    if annualize:
        vol *= (252 ** 0.5)  # 年化（交易日）
    return vol


def _calc_downside_volatility(returns, risk_free_daily=0.0, annualize=True):
    """计算下行波动率（只考虑低于目标收益的波动）"""
    downside = [r for r in returns if r < risk_free_daily]
    if len(downside) < 2:
        return 0.0
    mean = sum(downside) / len(downside)
    variance = sum((r - mean) ** 2 for r in downside) / (len(downside) - 1)
    vol = variance ** 0.5
    if annualize:
        vol *= (252 ** 0.5)
    return vol


def _calc_sharpe_ratio(returns, risk_free_rate=0.02):
    """计算夏普比率 = (年化收益 - 无风险利率) / 年化波动率"""
    if len(returns) < 2:
        return None
    ann_return = _calc_annualized_return_simple(returns)
    ann_vol = _calc_volatility(returns, annualize=True)
    if ann_vol <= 0:
        return None
    return (ann_return - risk_free_rate) / ann_vol


def _calc_sortino_ratio(returns, risk_free_rate=0.02):
    """计算索提诺比率 = (年化收益 - 无风险利率) / 下行波动率"""
    if len(returns) < 2:
        return None
    ann_return = _calc_annualized_return_simple(returns)
    daily_rf = risk_free_rate / 252
    down_vol = _calc_downside_volatility(returns, risk_free_daily=daily_rf, annualize=True)
    if down_vol <= 0:
        return None
    return (ann_return - risk_free_rate) / down_vol


def _calc_calmar_ratio(series):
    """计算卡尔马比率 = 年化收益 / 最大回撤"""
    if len(series) < 2:
        return None
    first_val = series[0]["value"]
    last_val = series[-1]["value"]
    if first_val <= 0:
        return None
    total_return = (last_val - first_val) / first_val
    days = len(series) - 1
    if days <= 0:
        return None
    ann_return = (1 + total_return) ** (365 / days) - 1
    max_dd = _calc_max_drawdown(series)
    if max_dd <= 0:
        return None
    return ann_return / max_dd


def _calc_annualized_return_simple(returns):
    """从日收益率序列计算年化收益率（几何法）"""
    if not returns:
        return 0.0
    cumulative = 1.0
    for r in returns:
        cumulative *= (1 + r)
    n_days = len(returns)
    if n_days <= 0:
        return 0.0
    ann = cumulative ** (252 / n_days) - 1  # 用交易日年化
    return ann


@router.get("/investment/performance-analysis")
async def get_performance_analysis(
    days: int = Query(default=365, ge=7, le=1825, description="回溯天数(7-1825)"),
    risk_free_rate: float = Query(default=0.02, ge=0, le=0.2, description="年化无风险利率"),
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """
    V2-023 高级收益率分析（组合绩效分析）
    
    提供：
    1. 风险调整收益指标：夏普比率、索提诺比率、卡尔马比率
    2. 风险指标：最大回撤、年化波动率、下行波动率
    3. 收益归因：按持仓的贡献度、按资产类型的分布
    4. 多时间段分析：近1周/1月/3月/6月/1年/YTD
    5. 日收益率序列（供前端图表使用）
    """
    # 1. 构建每日市值序列
    series = _build_daily_portfolio_series(db, days)
    
    if not series or all(p["value"] == 0 for p in series):
        return {
            "message": "无有效持仓数据",
            "days": days,
            "metrics": None,
        }
    
    # 过滤掉零值开头（可能前面没持仓）
    first_nonzero = 0
    for i, p in enumerate(series):
        if p["value"] > 0:
            first_nonzero = i
            break
    effective_series = series[first_nonzero:]
    
    if len(effective_series) < 2:
        return {
            "message": "数据点不足，无法计算绩效指标",
            "days": days,
            "metrics": None,
        }
    
    # 2. 计算日收益率
    daily_returns = _calc_daily_returns(effective_series)
    
    # 3. 计算各项指标
    max_dd = _calc_max_drawdown(effective_series)
    ann_vol = _calc_volatility(daily_returns, annualize=True)
    down_vol = _calc_downside_volatility(daily_returns, risk_free_daily=risk_free_rate / 252, annualize=True)
    sharpe = _calc_sharpe_ratio(daily_returns, risk_free_rate)
    sortino = _calc_sortino_ratio(daily_returns, risk_free_rate)
    calmar = _calc_calmar_ratio(effective_series)
    
    # 总收益和年化收益
    first_val = effective_series[0]["value"]
    last_val = effective_series[-1]["value"]
    total_return = (last_val - first_val) / first_val if first_val > 0 else 0
    eff_days = len(effective_series) - 1
    ann_return = (1 + total_return) ** (365 / eff_days) - 1 if eff_days > 0 else 0
    
    # 4. 收益归因（按持仓）
    positions = db.query(Position).filter(Position.status == "active").all()
    total_cost = sum(p.quantity * p.avg_cost for p in positions)
    total_value = sum(p.quantity * p.current_price for p in positions)
    
    position_attribution = []
    for p in positions:
        cost = p.quantity * p.avg_cost
        value = p.quantity * p.current_price
        profit = value - cost
        weight = cost / total_cost if total_cost > 0 else 0
        contribution = weight * (profit / cost) if cost > 0 else 0
        position_attribution.append({
            "position_id": p.id,
            "name": p.name,
            "type": p.position_type,
            "weight": round(weight * 100, 2),
            "return_pct": round((profit / cost * 100) if cost > 0 else 0, 2),
            "contribution": round(contribution * 100, 2),
            "profit": round(profit, 2),
        })
    
    # 按资产类型归因
    type_attribution = collections.defaultdict(lambda: {"cost": 0, "value": 0, "count": 0})
    for p in positions:
        t = type_attribution[p.position_type]
        t["cost"] += p.quantity * p.avg_cost
        t["value"] += p.quantity * p.current_price
        t["count"] += 1
    
    type_list = []
    for ptype, data in type_attribution.items():
        ret = (data["value"] - data["cost"]) / data["cost"] * 100 if data["cost"] > 0 else 0
        weight = data["cost"] / total_cost * 100 if total_cost > 0 else 0
        type_list.append({
            "type": ptype,
            "weight": round(weight, 2),
            "return_pct": round(ret, 2),
            "count": data["count"],
            "value": round(data["value"], 2),
        })
    
    # 5. 多时间段收益率
    def _period_return(series, lookback_days):
        if len(series) < 2:
            return None
        end_val = series[-1]["value"]
        target_idx = max(0, len(series) - 1 - lookback_days)
        start_val = series[target_idx]["value"]
        if start_val <= 0:
            return None
        return round((end_val - start_val) / start_val * 100, 2)
    
    period_returns = {
        "1w": _period_return(effective_series, 7),
        "1m": _period_return(effective_series, 30),
        "3m": _period_return(effective_series, 90),
        "6m": _period_return(effective_series, 180),
        "1y": _period_return(effective_series, 365),
        "ytd": _period_return(effective_series, eff_days),
    }
    
    # 6. 日收益率序列（降采样到最多90个点供前端使用）
    step = max(1, (len(daily_returns) + 89) // 90)  # ceiling division ensures ≤90 points
    chart_returns = [
        {"date": effective_series[i + 1]["date"], "return": round(r * 100, 4)}
        for i, r in enumerate(daily_returns)
        if i % step == 0
    ]
    
    # 7. 风险等级判定
    risk_level = "unknown"
    if sharpe is not None:
        if sharpe >= 1.5:
            risk_level = "excellent"
        elif sharpe >= 1.0:
            risk_level = "good"
        elif sharpe >= 0.5:
            risk_level = "moderate"
        elif sharpe >= 0:
            risk_level = "poor"
        else:
            risk_level = "danger"
    
    return {
        "days": days,
        "effective_days": eff_days,
        "metrics": {
            "total_return": round(total_return * 100, 2),
            "annualized_return": round(ann_return * 100, 2),
            "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
            "sortino_ratio": round(sortino, 3) if sortino is not None else None,
            "calmar_ratio": round(calmar, 3) if calmar is not None else None,
            "max_drawdown": round(max_dd * 100, 2),
            "annualized_volatility": round(ann_vol * 100, 2),
            "downside_volatility": round(down_vol * 100, 2),
            "risk_free_rate": round(risk_free_rate * 100, 2),
            "risk_level": risk_level,
        },
        "attribution": {
            "by_position": position_attribution,
            "by_type": type_list,
        },
        "period_returns": period_returns,
        "summary": {
            "total_value": round(last_val, 2),
            "total_cost": round(first_val, 2),
            "total_profit": round(last_val - first_val, 2),
            "position_count": len(positions),
        },
        "chart_data": chart_returns,
    }


# ============================================================
# V2-024: 风险分析 (Risk Analysis)
# ============================================================


def _calc_var_historical(returns, confidence=0.95):
    """历史模拟法计算 VaR (Value at Risk)"""
    if len(returns) < 10:
        return None
    sorted_returns = sorted(returns)
    index = int((1 - confidence) * len(sorted_returns))
    index = max(0, min(index, len(sorted_returns) - 1))
    return sorted_returns[index]


def _calc_cvar(returns, confidence=0.95):
    """CVaR (Expected Shortfall) = VaR 以下的平均损失"""
    if len(returns) < 10:
        return None
    sorted_returns = sorted(returns)
    cutoff = int((1 - confidence) * len(sorted_returns))
    cutoff = max(1, cutoff)
    tail = sorted_returns[:cutoff]
    return sum(tail) / len(tail)


def _calc_drawdown_details(series):
    """详细回撤分析：当前回撤、最大回撤、平均回撤持续时间、最长回撤期"""
    if not series or len(series) < 2:
        return {
            "current_drawdown": 0,
            "max_drawdown": 0,
            "max_drawdown_start": None,
            "max_drawdown_end": None,
            "avg_recovery_days": None,
            "longest_drawdown_days": 0,
            "drawdown_periods": [],
        }
    
    # 计算每日回撤序列
    peak = series[0]["value"]
    drawdowns = []
    in_drawdown = False
    dd_start = None
    periods = []
    max_dd = 0.0
    max_dd_start = None
    max_dd_end = None
    
    for i, point in enumerate(series):
        val = point["value"]
        if val >= peak:
            if in_drawdown and dd_start is not None:
                # 回撤恢复
                duration = i - dd_start
                periods.append({
                    "start": series[dd_start]["date"],
                    "end": point["date"],
                    "duration_days": duration,
                    "max_drawdown": round(max(drawdowns[dd_start:i]) if dd_start < len(drawdowns) else 0, 4),
                })
                in_drawdown = False
            peak = val
            drawdowns.append(0.0)
        else:
            dd = (peak - val) / peak if peak > 0 else 0
            drawdowns.append(dd)
            if not in_drawdown:
                in_drawdown = True
                dd_start = i - 1  # peak day
            if dd > max_dd:
                max_dd = dd
                max_dd_start = series[dd_start]["date"] if dd_start is not None else None
                max_dd_end = point["date"]
    
    # 如果当前仍在回撤中
    current_dd = drawdowns[-1] if drawdowns else 0.0
    if in_drawdown and dd_start is not None:
        duration = len(series) - 1 - dd_start
        periods.append({
            "start": series[dd_start]["date"],
            "end": series[-1]["date"],
            "duration_days": duration,
            "max_drawdown": round(max(drawdowns[dd_start:]) if dd_start < len(drawdowns) else 0, 4),
            "recovered": False,
        })
    
    # 标记已恢复的期间
    for p in periods:
        if "recovered" not in p:
            p["recovered"] = True
    
    # 统计
    recovered_durations = [p["duration_days"] for p in periods if p.get("recovered", True)]
    avg_recovery = sum(recovered_durations) / len(recovered_durations) if recovered_durations else None
    longest = max((p["duration_days"] for p in periods), default=0)
    
    return {
        "current_drawdown": round(current_dd * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "max_drawdown_start": max_dd_start,
        "max_drawdown_end": max_dd_end,
        "avg_recovery_days": round(avg_recovery, 1) if avg_recovery else None,
        "longest_drawdown_days": longest,
        "drawdown_periods": periods[:10],  # 最多返回10个
    }


def _calc_rolling_metrics(daily_returns, dates, window=30):
    """滚动指标：滚动夏普、滚动波动率"""
    if len(daily_returns) < window:
        return {"rolling_sharpe": [], "rolling_volatility": []}
    
    rolling_sharpe = []
    rolling_vol = []
    
    for i in range(window - 1, len(daily_returns)):
        window_returns = daily_returns[i - window + 1:i + 1]
        # 滚动年化波动率
        mean = sum(window_returns) / len(window_returns)
        variance = sum((r - mean) ** 2 for r in window_returns) / (len(window_returns) - 1)
        vol = (variance ** 0.5) * (252 ** 0.5)
        
        # 滚动年化收益
        ann_ret = (1 + mean) ** 252 - 1
        
        # 滚动夏普
        sharpe = (ann_ret - 0.02) / vol if vol > 0 else 0
        
        rolling_sharpe.append({"date": dates[i + 1], "value": round(sharpe, 3)})
        rolling_vol.append({"date": dates[i + 1], "value": round(vol * 100, 2)})
    
    # 降采样到最多60个点
    step = max(1, len(rolling_sharpe) // 60)
    return {
        "rolling_sharpe": rolling_sharpe[::step],
        "rolling_volatility": rolling_vol[::step],
    }


def _calc_stress_test(total_value, positions):
    """压力测试：模拟极端市场情景"""
    scenarios = [
        {"name": "温和下跌", "emoji": "🟡", "shock": -0.05, "description": "市场温和调整，主要指数下跌5%"},
        {"name": "中度回调", "emoji": "🟠", "shock": -0.10, "description": "经济数据不及预期，市场回调10%"},
        {"name": "大幅下跌", "emoji": "🔴", "shock": -0.20, "description": "黑天鹅事件，市场恐慌性下跌20%"},
        {"name": "极端崩盘", "emoji": "💀", "shock": -0.30, "description": "系统性风险，类似2008年金融危机"},
        {"name": "利率急升", "emoji": "📈", "shock": -0.08, "description": "央行大幅加息，债券/成长股承压"},
    ]
    
    results = []
    for s in scenarios:
        loss = total_value * s["shock"]
        remaining = total_value + loss
        results.append({
            "name": s["name"],
            "emoji": s["emoji"],
            "description": s["description"],
            "shock_pct": round(s["shock"] * 100, 1),
            "estimated_loss": round(loss, 2),
            "remaining_value": round(max(0, remaining), 2),
        })
    
    return results


def _calc_risk_grade(var_95, max_dd, sharpe, vol, current_dd):
    """综合风险评级 A-F"""
    score = 100
    
    # VaR 评分 (25分)
    if var_95 is not None:
        var_abs = abs(var_95)
        if var_abs <= 0.01:
            score += 0  # 很好
        elif var_abs <= 0.02:
            score -= 5
        elif var_abs <= 0.03:
            score -= 10
        elif var_abs <= 0.05:
            score -= 15
        else:
            score -= 25
    
    # 最大回撤评分 (25分)
    if max_dd is not None:
        dd_pct = max_dd
        if dd_pct <= 5:
            score += 0
        elif dd_pct <= 10:
            score -= 5
        elif dd_pct <= 20:
            score -= 10
        elif dd_pct <= 30:
            score -= 15
        else:
            score -= 25
    
    # 夏普比率评分 (25分)
    if sharpe is not None:
        if sharpe >= 1.5:
            score += 0
        elif sharpe >= 1.0:
            score -= 5
        elif sharpe >= 0.5:
            score -= 10
        elif sharpe >= 0:
            score -= 15
        else:
            score -= 25
    
    # 当前回撤评分 (25分)
    if current_dd is not None:
        if current_dd <= 3:
            score += 0
        elif current_dd <= 5:
            score -= 5
        elif current_dd <= 10:
            score -= 10
        elif current_dd <= 20:
            score -= 15
        else:
            score -= 25
    
    score = max(0, min(100, score))
    
    if score >= 85:
        grade = "A"
        label = "低风险"
        emoji = "🟢"
    elif score >= 70:
        grade = "B"
        label = "中低风险"
        emoji = "🔵"
    elif score >= 55:
        grade = "C"
        label = "中等风险"
        emoji = "🟡"
    elif score >= 40:
        grade = "D"
        label = "中高风险"
        emoji = "🟠"
    else:
        grade = "F"
        label = "高风险"
        emoji = "🔴"
    
    return {
        "grade": grade,
        "label": label,
        "emoji": emoji,
        "score": score,
    }


@router.get("/investment/risk-analysis")
async def get_risk_analysis(
    days: int = Query(default=365, ge=30, le=1825, description="回溯天数(30-1825)"),
    confidence: float = Query(default=0.95, ge=0.90, le=0.99, description="VaR置信度(0.90-0.99)"),
    risk_free_rate: float = Query(default=0.02, ge=0, le=0.2, description="年化无风险利率"),
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """
    V2-024 深度风险分析
    
    提供比 performance-analysis 更深入的风险评估：
    1. VaR (Value at Risk) - 历史模拟法，95%/99% 置信度
    2. CVaR (Expected Shortfall) - 尾部风险
    3. 详细回撤分析 - 当前回撤/最大回撤/恢复时间/回撤期列表
    4. 滚动指标 - 30日滚动夏普/滚动波动率（图表数据）
    5. 压力测试 - 5种极端情景模拟
    6. 风险分解 - 各持仓对组合风险的贡献
    7. 综合风险评级 - A-F 五级
    """
    # 1. 构建每日市值序列
    series = _build_daily_portfolio_series(db, days)
    
    if not series or all(p["value"] == 0 for p in series):
        return {
            "message": "无有效持仓数据",
            "days": days,
            "risk_metrics": None,
        }
    
    # 过滤零值
    first_nonzero = 0
    for i, p in enumerate(series):
        if p["value"] > 0:
            first_nonzero = i
            break
    effective_series = series[first_nonzero:]
    
    if len(effective_series) < 10:
        return {
            "message": "数据点不足，无法进行风险分析",
            "days": days,
            "risk_metrics": None,
        }
    
    # 2. 计算日收益率
    daily_returns = _calc_daily_returns(effective_series)
    dates = [p["date"] for p in effective_series]
    
    # 3. VaR & CVaR
    var_95 = _calc_var_historical(daily_returns, 0.95)
    var_99 = _calc_var_historical(daily_returns, 0.99)
    cvar_95 = _calc_cvar(daily_returns, 0.95)
    cvar_99 = _calc_cvar(daily_returns, 0.99)
    
    # 4. 回撤详细分析
    dd_details = _calc_drawdown_details(effective_series)
    
    # 5. 滚动指标
    rolling = _calc_rolling_metrics(daily_returns, dates, window=30)
    
    # 6. 基础指标（复用 helper）
    max_dd = _calc_max_drawdown(effective_series)
    ann_vol = _calc_volatility(daily_returns, annualize=True)
    sharpe = _calc_sharpe_ratio(daily_returns, risk_free_rate)
    down_vol = _calc_downside_volatility(daily_returns, risk_free_daily=risk_free_rate / 252, annualize=True)
    
    # 7. 压力测试
    current_value = effective_series[-1]["value"]
    positions = db.query(Position).filter(Position.status == "active").all()
    stress = _calc_stress_test(current_value, positions)
    
    # 8. 风险分解（按持仓）
    total_cost = sum(p.quantity * p.avg_cost for p in positions)
    total_value_pos = sum(p.quantity * p.current_price for p in positions)
    
    risk_decomposition = []
    for p in positions:
        cost = p.quantity * p.avg_cost
        value = p.quantity * p.current_price
        weight = cost / total_cost if total_cost > 0 else 0
        pnl_pct = (value - cost) / cost * 100 if cost > 0 else 0
        
        # 简化风险贡献：按权重 * 波动率估算
        # 更精确需要协方差矩阵，这里用权重近似
        risk_contribution = weight * ann_vol
        
        risk_decomposition.append({
            "position_id": p.id,
            "name": p.name,
            "type": p.position_type,
            "weight": round(weight * 100, 2),
            "value": round(value, 2),
            "pnl_pct": round(pnl_pct, 2),
            "risk_contribution": round(risk_contribution * 100, 2),
        })
    
    # 按风险贡献排序
    risk_decomposition.sort(key=lambda x: x["risk_contribution"], reverse=True)
    
    # 9. 综合风险评级
    risk_grade = _calc_risk_grade(
        var_95=abs(var_95) if var_95 is not None else None,
        max_dd=max_dd * 100,
        sharpe=sharpe,
        vol=ann_vol,
        current_dd=dd_details["current_drawdown"],
    )
    
    # 10. 收益分布统计
    positive_days = sum(1 for r in daily_returns if r > 0)
    negative_days = sum(1 for r in daily_returns if r < 0)
    total_days = len(daily_returns)
    
    avg_gain = sum(r for r in daily_returns if r > 0) / positive_days if positive_days > 0 else 0
    avg_loss = sum(r for r in daily_returns if r < 0) / negative_days if negative_days > 0 else 0
    
    best_day = max(daily_returns) if daily_returns else 0
    worst_day = min(daily_returns) if daily_returns else 0
    
    distribution = {
        "total_days": total_days,
        "positive_days": positive_days,
        "negative_days": negative_days,
        "zero_days": total_days - positive_days - negative_days,
        "positive_pct": round(positive_days / total_days * 100, 1) if total_days > 0 else 0,
        "avg_daily_gain": round(avg_gain * 100, 4),
        "avg_daily_loss": round(avg_loss * 100, 4),
        "best_day": round(best_day * 100, 4),
        "worst_day": round(worst_day * 100, 4),
        "gain_loss_ratio": round(abs(avg_gain / avg_loss), 2) if avg_loss != 0 else None,
    }
    
    # 11. 风险建议
    recommendations = []
    if dd_details["current_drawdown"] > 10:
        recommendations.append("⚠️ 当前回撤超过10%，建议审视持仓集中度，考虑分散投资")
    if var_95 is not None and abs(var_95) > 0.03:
        recommendations.append("🔴 日VaR超过3%，单日波动较大，建议增加低风险资产配置")
    if ann_vol > 0.3:
        recommendations.append("📊 年化波动率超过30%，组合波动较大，可考虑配置债券/货币基金平滑波动")
    if sharpe is not None and sharpe < 0.5:
        recommendations.append("📉 夏普比率偏低，风险调整后的收益不理想，建议优化持仓结构")
    if len(positions) <= 2 and total_value_pos > 0:
        recommendations.append("🎯 持仓集中度过高（仅{}只），建议分散到3-5只标的".format(len(positions)))
    if not recommendations:
        recommendations.append("✅ 风险指标整体健康，继续保持当前配置")
    
    return {
        "days": days,
        "effective_days": len(effective_series),
        "confidence_level": confidence,
        "risk_grade": risk_grade,
        "var": {
            "var_95": round(var_95 * 100, 4) if var_95 is not None else None,
            "var_99": round(var_99 * 100, 4) if var_99 is not None else None,
            "cvar_95": round(cvar_95 * 100, 4) if cvar_95 is not None else None,
            "cvar_99": round(cvar_99 * 100, 4) if cvar_99 is not None else None,
            "interpretation": f"在{confidence*100:.0f}%置信度下，单日最大预期损失为{round(abs(var_95 or 0)*100, 2)}%",
        },
        "drawdown": dd_details,
        "risk_metrics": {
            "annualized_volatility": round(ann_vol * 100, 2),
            "downside_volatility": round(down_vol * 100, 2),
            "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
            "max_drawdown": round(max_dd * 100, 2),
            "current_drawdown": dd_details["current_drawdown"],
        },
        "distribution": distribution,
        "stress_test": stress,
        "risk_decomposition": risk_decomposition,
        "rolling_metrics": rolling,
        "recommendations": recommendations,
        "portfolio_value": round(current_value, 2),
    }


# ===== V2-025: 实时增量备份 =====

import json
import gzip
from pathlib import Path

# 备份目录
