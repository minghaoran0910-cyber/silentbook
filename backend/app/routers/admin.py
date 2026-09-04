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

class LogQueryParams(BaseModel):
    level: Optional[str] = None
    module: Optional[str] = None
    search: Optional[str] = None
    since_minutes: Optional[int] = Field(default=60, description="查询最近N分钟的日志")
    limit: int = Field(default=100, ge=1, le=1000)


@router.get("/admin/logs")
async def query_logs(
    level: Optional[str] = None,
    module: Optional[str] = None,
    search: Optional[str] = None,
    since_minutes: int = 60,
    limit: int = 100,
    user: User = Depends(require_user)
):
    """
    查询系统日志（内存缓冲区）
    
    支持过滤：
    - level: DEBUG/INFO/WARNING/ERROR/CRITICAL
    - module: 模块名（模糊匹配）
    - search: 消息内容搜索
    - since_minutes: 查询最近N分钟（默认60）
    - limit: 返回条数上限（默认100，最大1000）
    """
    since = None
    if since_minutes:
        since = time.time() - (since_minutes * 60)
    
    records = log_buffer.query(
        level=level,
        module=module,
        since=since,
        limit=min(limit, 1000),
        search=search
    )
    
    return {
        "count": len(records),
        "logs": records,
        "filters": {
            "level": level,
            "module": module,
            "search": search,
            "since_minutes": since_minutes
        }
    }


@router.get("/admin/logs/stats")
async def log_stats(user: User = Depends(require_user)):
    """
    日志统计信息
    
    返回：
    - 总记录数 / 缓冲区容量
    - 按级别分布
    - 按模块分布
    - 时间范围
    """
    return log_buffer.stats()


@router.post("/admin/logs/clear")
async def clear_logs(user: User = Depends(require_user)):
    """清空日志缓冲区（调试用）"""
    log_buffer.clear()
    logger.info("日志缓冲区已清空")
    return {"message": "日志缓冲区已清空"}


# ===== 协作 API（给墨砚/远瞻等本地 Agent 用，无需认证） =====

from ..database import Position


def _verify_collaboration_key(request: Request):
    """协作接口共享密钥校验（可选，配置 COLLABORATION_SECRET 后启用）"""
    secret = os.getenv("COLLABORATION_SECRET", "")
    if not secret:
        return
    supplied = request.headers.get("x-collaboration-key", "")
    if not supplied or not hmac.compare_digest(secret, supplied):
        raise HTTPException(status_code=403, detail="Invalid collaboration key")


def _set_collaboration_tenant():
    """协作接口设置租户上下文（默认用户 1，可配置）"""
    user_id = int(os.getenv("COLLABORATION_USER_ID", os.getenv("WEBHOOK_USER_ID", "1")))
    set_tenant_user_id(user_id)


@router.get("/collaboration/moyan/consumption")
async def collaboration_moyan_consumption(request: Request, days: int = Query(default=7, le=90), db: Session = Depends(get_db)):
    """
    墨砚专用：获取消费数据
    
    返回最近 N 天的交易记录，供墨砚分析和记账使用
    """
    _verify_collaboration_key(request)
    _set_collaboration_tenant()
    cutoff = datetime.utcnow() - timedelta(days=days)
    transactions = db.query(Transaction).filter(
        Transaction.parsed_at >= cutoff
    ).order_by(Transaction.parsed_at.desc()).all()
    
    # 按分类统计
    by_category = {}
    total_expense = 0
    total_income = 0
    
    for tx in transactions:
        cat = tx.category or "其他"
        if cat not in by_category:
            by_category[cat] = {"count": 0, "amount": 0}
        by_category[cat]["count"] += 1
        by_category[cat]["amount"] += tx.amount
        
        if tx.transaction_type == "expense":
            total_expense += tx.amount
        elif tx.transaction_type == "income":
            total_income += tx.amount
    
    return {
        "days": days,
        "total_transactions": len(transactions),
        "total_expense": round(total_expense, 2),
        "total_income": round(total_income, 2),
        "net": round(total_income - total_expense, 2),
        "by_category": by_category,
        "recent_transactions": [
            {
                "id": tx.id,
                "amount": tx.amount,
                "category": tx.category,
                "account": tx.account,
                "description": tx.description,
                "type": tx.transaction_type,
                "parsed_at": tx.parsed_at.isoformat() if tx.parsed_at else None
            }
            for tx in transactions[:20]  # 最近 20 条
        ],
        "updated_at": datetime.utcnow().isoformat()
    }


@router.get("/collaboration/yuanzhan/investment")
async def collaboration_yuanzhan_investment(request: Request, db: Session = Depends(get_db)):
    """
    远瞻专用：获取投资数据
    
    返回持仓、资产、收益等投资相关数据
    """
    _verify_collaboration_key(request)
    _set_collaboration_tenant()
    # 获取所有活跃持仓
    positions = db.query(Position).filter(
        Position.status == "active"
    ).order_by(Position.updated_at.desc()).all()
    
    # 计算总市值和收益
    total_market_value = 0
    total_cost = 0
    positions_data = []
    
    for pos in positions:
        market_value = (pos.current_price or 0) * (pos.quantity or 0)
        cost_value = (pos.avg_cost or 0) * (pos.quantity or 0)
        profit = market_value - cost_value
        profit_pct = (profit / cost_value * 100) if cost_value > 0 else 0
        
        total_market_value += market_value
        total_cost += cost_value
        
        positions_data.append({
            "id": pos.id,
            "name": pos.name,
            "symbol": pos.symbol,
            "type": pos.position_type,
            "quantity": pos.quantity,
            "avg_cost": pos.avg_cost,
            "current_price": pos.current_price,
            "market_value": round(market_value, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "account": pos.account,
            "updated_at": pos.updated_at.isoformat() if pos.updated_at else None
        })
    
    total_profit = total_market_value - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
    
    # 按类型统计
    by_type = {}
    for pos in positions_data:
        t = pos["type"] or "other"
        if t not in by_type:
            by_type[t] = {"count": 0, "market_value": 0, "profit": 0}
        by_type[t]["count"] += 1
        by_type[t]["market_value"] += pos["market_value"]
        by_type[t]["profit"] += pos["profit"]
    
    return {
        "total_positions": len(positions),
        "total_market_value": round(total_market_value, 2),
        "total_cost": round(total_cost, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "by_type": {k: {"count": v["count"], "market_value": round(v["market_value"], 2), "profit": round(v["profit"], 2)} for k, v in by_type.items()},
        "positions": positions_data,
        "updated_at": datetime.utcnow().isoformat()
    }


@router.get("/collaboration/hao-ran-life/markdown")
async def collaboration_hao_ran_life(request: Request, db: Session = Depends(get_db)):
    """
    生活全景：Markdown 格式的综合数据
    
    供老油条/墨砚/远瞻共享使用
    """
    _verify_collaboration_key(request)
    _set_collaboration_tenant()
    # 最近 7 天消费
    cutoff_7d = datetime.utcnow() - timedelta(days=7)
    recent_txs = db.query(Transaction).filter(
        Transaction.parsed_at >= cutoff_7d
    ).order_by(Transaction.parsed_at.desc()).limit(50).all()
    
    total_expense_7d = sum(tx.amount for tx in recent_txs if tx.transaction_type == "expense")
    
    # 持仓
    positions = db.query(Position).filter(Position.status == "active").all()
    total_market_value = sum((p.current_price or 0) * (p.quantity or 0) for p in positions)
    total_cost = sum((p.avg_cost or 0) * (p.quantity or 0) for p in positions)
    total_profit = total_market_value - total_cost
    
    # 生成 Markdown
    md = f"""# 浩然生活全景

*更新时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC*

## 💰 财务概况

### 最近 7 天消费
- 总支出: ¥{total_expense_7d:.2f}
- 交易笔数: {len(recent_txs)}

### 投资组合
- 持仓数量: {len(positions)} 个
- 总市值: ¥{total_market_value:,.2f}
- 总成本: ¥{total_cost:,.2f}
- 总收益: ¥{total_profit:,.2f} ({total_profit/total_cost*100 if total_cost > 0 else 0:.2f}%)

## 📊 最近交易

| 日期 | 分类 | 金额 | 账户 | 说明 |
|------|------|------|------|------|
"""
    for tx in recent_txs[:10]:
        date_str = tx.parsed_at.strftime('%m-%d %H:%M') if tx.parsed_at else '-'
        md += f"| {date_str} | {tx.category or '-'} | ¥{tx.amount:.2f} | {tx.account or '-'} | {tx.description or '-'} |\n"
    
    md += "\n## 📈 持仓明细\n\n"
    md += "| 名称 | 类型 | 市值 | 收益 | 收益率 |\n"
    md += "|------|------|------|------|--------|\n"
    
    for pos in sorted(positions, key=lambda p: (p.current_price or 0) * (p.quantity or 0), reverse=True)[:10]:
        mv = (pos.current_price or 0) * (pos.quantity or 0)
        cost = (pos.avg_cost or 0) * (pos.quantity or 0)
        profit = mv - cost
        pct = profit / cost * 100 if cost > 0 else 0
        md += f"| {pos.name[:20]} | {pos.position_type or '-'} | ¥{mv:,.0f} | ¥{profit:,.0f} | {pct:.1f}% |\n"
    
    return {"markdown": md, "updated_at": datetime.utcnow().isoformat()}
