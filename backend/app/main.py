from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
from .database import get_db, SessionLocal, Transaction, AnalysisResult, Asset, Liability, AgentConfig, Setting, init_db
from .schemas import (
    TransactionCreate, TransactionUpdate, TransactionResponse,
    AnalysisResponse, DashboardStats,
    AssetCreate, AssetUpdate, AssetResponse,
    LiabilityCreate, LiabilityUpdate, LiabilityResponse
)
import httpx
import os
import logging
import time
import collections
from .scheduler import create_scheduler

# CORS - 开发环境允许所有，生产环境需要配置
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5000")
PARSER_API_URL = os.getenv("PARSER_API_URL", "http://localhost:6000")

# ===== API 限流 =====
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds
_request_log = collections.defaultdict(collections.deque)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    # 跳过健康检查
    if request.url.path in ["/health", "/"]:
        return await call_next(request)
    
    # 清理过期记录
    log = _request_log[client_ip]
    while log and log[0] < now - RATE_LIMIT_WINDOW:
        log.popleft()
    
    if len(log) >= RATE_LIMIT_REQUESTS:
        return JSONResponse(
            status_code=429,
            content={"detail": f"请求过于频繁，每{RATE_LIMIT_WINDOW}秒限{RATE_LIMIT_REQUESTS}次"}
        )
    
    log.append(now)
    return await call_next(request)


logger = logging.getLogger("silentbook")
_scheduler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    # Startup
    init_db()
    _scheduler = create_scheduler()
    _scheduler.start()
    logger.info("定时任务调度器已启动")
    yield
    # Shutdown
    _scheduler.shutdown(wait=False)
    logger.info("定时任务调度器已关闭")

app = FastAPI(title="SilentBook API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "SilentBook API", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ===== 交易管理 =====

@app.post("/transactions", response_model=TransactionResponse)
async def create_transaction(transaction: TransactionCreate, db: Session = Depends(get_db)):
    """创建交易记录（手动或自动）"""
    db_transaction = Transaction(
        amount=transaction.amount,
        category=transaction.category,
        account=transaction.account,
        description=transaction.description,
        transaction_type=transaction.transaction_type,
        raw_text=transaction.raw_text,
        confidence=transaction.confidence,
        parsed_at=datetime.utcnow()
    )
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction


@app.get("/transactions", response_model=List[TransactionResponse])
async def list_transactions(
    skip: int = 0,
    limit: int = Query(default=100, le=1000),
    account: Optional[str] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取交易列表"""
    query = db.query(Transaction)
    if account:
        query = query.filter(Transaction.account == account)
    if category:
        query = query.filter(Transaction.category == category)
    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)
    return query.order_by(Transaction.parsed_at.desc()).offset(skip).limit(limit).all()


@app.get("/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """获取单个交易"""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction


@app.put("/transactions/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: int,
    transaction: TransactionUpdate,
    db: Session = Depends(get_db)
):
    """更新交易记录"""
    db_transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    update_data = transaction.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_transaction, field, value)

    db.commit()
    db.refresh(db_transaction)
    return db_transaction


@app.delete("/transactions/{transaction_id}")
async def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """删除交易"""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(transaction)
    db.commit()
    return {"message": "Transaction deleted"}


@app.delete("/transactions")
async def delete_all_transactions(confirm: bool = Query(False), db: Session = Depends(get_db)):
    """清空所有交易（需要确认）"""
    if not confirm:
        raise HTTPException(status_code=400, detail="需要确认参数 confirm=true")
    count = db.query(Transaction).count()
    db.query(Transaction).delete()
    db.commit()
    return {"message": f"Deleted {count} transactions"}


# ===== 通知解析 =====

@app.post("/parse")
async def parse_notification(notification: dict):
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
                db.commit()
                db.refresh(db_transaction)
                return {"message": "Transaction created", "id": db_transaction.id}
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

@app.post("/webhook/notify")
async def webhook_notify(req: WebhookRequest, db: Session = Depends(get_db)):
    """接收通知 webhook，自动解析并存入交易记录"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{PARSER_API_URL}/parse",
                json={"title": req.title, "body": req.body, "source": req.source, "timestamp": req.timestamp},
                timeout=10.0
            )
            response.raise_for_status()
            parsed = response.json()
            
            required = ["amount", "category", "account", "transaction_type"]
            for field in required:
                if field not in parsed:
                    return {"status": "skipped", "reason": f"缺少字段: {field}", "raw": parsed}
            
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
            db.commit()
            db.refresh(db_tx)
            
            return {
                "status": "created",
                "id": db_tx.id,
                "amount": db_tx.amount,
                "category": db_tx.category,
                "type": db_tx.transaction_type,
                "confidence": db_tx.confidence,
                "abnormal_alert": await check_abnormal_and_analyze(db_tx, db)
            }
        except httpx.RequestError:
            return {"status": "error", "reason": "通知解析器不可用"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}


@app.post("/webhook/notify/batch")
async def webhook_notify_batch(items: List[WebhookRequest], db: Session = Depends(get_db)):
    """批量接收通知"""
    results = []
    for item in items:
        result = await webhook_notify(item, db)
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
        
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{AGENT_API_URL}/analyze",
                json={"transactions": tx_data},
                timeout=90.0
            )
            if resp.status_code == 200:
                result = resp.json()
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

@app.get("/stats/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(db: Session = Depends(get_db)):
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

    # 净资产 = 交易净额 + 资产 - 负债
    net_assets = (total_income - total_expenses) + total_assets - total_liabilities

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


@app.get("/stats/trend")
async def get_trend(days: int = 30, db: Session = Depends(get_db)):
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


@app.get("/stats/monthly")
async def get_monthly_report(year: int = None, month: int = None, db: Session = Depends(get_db)):
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

@app.get("/stats/daily")
async def get_daily_report(date: str = None, db: Session = Depends(get_db)):
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


@app.get("/stats/weekly")
async def get_weekly_report(week_offset: int = 0, db: Session = Depends(get_db)):
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


@app.get("/stats/yearly")
async def get_yearly_report(year: int = None, db: Session = Depends(get_db)):
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


@app.get("/stats/asset-curve")
async def get_asset_curve(months: int = 12, db: Session = Depends(get_db)):
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

@app.get("/export/csv")
async def export_csv(db: Session = Depends(get_db)):
    """导出交易记录为 CSV"""
    import csv
    import io
    from fastapi.responses import StreamingResponse
    
    transactions = db.query(Transaction).order_by(Transaction.parsed_at.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["日期", "类型", "金额", "分类", "账户", "描述", "置信度"])
    for t in transactions:
        writer.writerow([
            t.parsed_at.strftime("%Y-%m-%d %H:%M") if t.parsed_at else "",
            t.transaction_type,
            t.amount,
            t.category,
            t.account,
            t.description or "",
            t.confidence
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=silentbook_transactions.csv"}
    )


@app.post("/import/csv")
async def import_csv(file: dict, db: Session = Depends(get_db)):
    """导入 CSV 交易记录"""
    import csv
    import io
    
    content = file.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    
    reader = csv.DictReader(io.StringIO(content))
    imported = 0
    skipped = 0
    for row in reader:
        try:
            amount = float(row.get("金额", 0))
            if amount <= 0:
                skipped += 1
                continue
            
            tx = Transaction(
                amount=amount,
                category=row.get("分类", "其他"),
                account=row.get("账户", ""),
                description=row.get("描述", ""),
                transaction_type=row.get("类型", "expense"),
                confidence=float(row.get("置信度", 1.0)),
                parsed_at=datetime.utcnow()
            )
            db.add(tx)
            imported += 1
        except Exception:
            skipped += 1
    
    db.commit()
    return {"imported": imported, "skipped": skipped}


# ===== 预算管理 =====

class BudgetCreate(BaseModel):
    category: str
    monthly_limit: float
    alert_threshold: float = 0.8

class BudgetResponse(BaseModel):
    id: int
    category: str
    monthly_limit: float
    alert_threshold: float
    current_spent: float
    usage_rate: float
    class Config:
        from_attributes = True

# 预算存储在 Setting 表中（JSON 格式）
@app.get("/budgets", response_model=List[dict])
async def get_budgets(db: Session = Depends(get_db)):
    """获取所有预算"""
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if not raw or not raw.value:
        return []
    
    import json
    budgets = json.loads(raw.value)
    
    # 计算当月已花
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    result = []
    for b in budgets:
        spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.category == b["category"],
            Transaction.transaction_type == "expense",
            Transaction.parsed_at >= month_start
        ).scalar() or 0.0
        
        usage = float(spent) / b["monthly_limit"] if b["monthly_limit"] > 0 else 0
        result.append({
            **b,
            "current_spent": round(float(spent), 2),
            "usage_rate": round(usage * 100, 1),
            "alert": usage >= b.get("alert_threshold", 0.8)
        })
    return result


@app.post("/budgets")
async def create_budget(budget: BudgetCreate, db: Session = Depends(get_db)):
    """创建/更新预算"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if raw:
        budgets = json.loads(raw.value)
    else:
        budgets = []
    
    # 检查是否已存在该分类的预算
    existing = next((b for b in budgets if b["category"] == budget.category), None)
    if existing:
        existing["monthly_limit"] = budget.monthly_limit
        existing["alert_threshold"] = budget.alert_threshold
    else:
        budgets.append(budget.model_dump())
    
    if raw:
        raw.value = json.dumps(budgets)
    else:
        db.add(Setting(key="budgets", value=json.dumps(budgets)))
    db.commit()
    return {"status": "ok", "budgets": budgets}


@app.delete("/budgets/{category}")
async def delete_budget(category: str, db: Session = Depends(get_db)):
    """删除预算"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if not raw:
        raise HTTPException(status_code=404, detail="无预算数据")
    
    budgets = json.loads(raw.value)
    budgets = [b for b in budgets if b["category"] != category]
    raw.value = json.dumps(budgets)
    db.commit()
    return {"status": "ok", "remaining": len(budgets)}


# ===== 首次使用引导 =====

@app.get("/onboarding/status")
async def get_onboarding_status(db: Session = Depends(get_db)):
    """检查是否需要引导"""
    tx_count = db.query(Transaction).count()
    asset_count = db.query(Asset).count()
    
    return {
        "needs_onboarding": tx_count == 0 and asset_count == 0,
        "has_transactions": tx_count > 0,
        "has_assets": asset_count > 0,
        "transaction_count": tx_count,
        "asset_count": asset_count
    }


@app.post("/onboarding/init")
async def init_first_data(data: dict, db: Session = Depends(get_db)):
    """首次使用：录入初始资产"""
    assets = data.get("assets", [])
    for a in assets:
        asset = Asset(
            name=a.get("name", ""),
            asset_type=a.get("asset_type", "cash"),
            current_value=a.get("current_value", 0),
            initial_value=a.get("initial_value", a.get("current_value", 0)),
            status="active"
        )
        db.add(asset)
    
    db.commit()
    return {"status": "ok", "assets_created": len(assets)}


# ===== 用户认证（基础 JWT） =====

@app.post("/auth/setup")
async def setup_auth(data: dict, db: Session = Depends(get_db)):
    """设置访问密码"""
    import hashlib
    password = data.get("password", "")
    if not password or len(password) < 4:
        raise HTTPException(status_code=400, detail="密码至少4位")
    
    hashed = hashlib.sha256(password.encode()).hexdigest()
    existing = db.query(Setting).filter(Setting.key == "auth_password").first()
    if existing:
        existing.value = hashed
    else:
        db.add(Setting(key="auth_password", value=hashed))
    db.commit()
    return {"status": "ok"}


@app.post("/auth/verify")
async def verify_auth(data: dict, db: Session = Depends(get_db)):
    """验证密码，返回 token"""
    import hashlib
    import time
    password = data.get("password", "")
    hashed = hashlib.sha256(password.encode()).hexdigest()
    
    stored = db.query(Setting).filter(Setting.key == "auth_password").first()
    if not stored:
        return {"auth_enabled": False}
    
    if hashed != stored.value:
        raise HTTPException(status_code=401, detail="密码错误")
    
    token = hashlib.md5(f"{password}{time.time()}".encode()).hexdigest()
    return {"auth_enabled": True, "token": token}


# ===== Agent 分析 =====

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(db: Session = Depends(get_db)):
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
                timeout=90.0
            )
            result = response.json()
        except Exception as e:
            result = {
                "consumption": "Agent 服务暂不可用",
                "investment": "Agent 服务暂不可用",
                "suggestion": "请检查 Agent 服务状态"
            }

    # 保存分析结果
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


@app.get("/analysis/latest", response_model=AnalysisResponse)
async def get_latest_analysis(db: Session = Depends(get_db)):
    """获取最新分析结果"""
    latest = db.query(AnalysisResult).order_by(AnalysisResult.created_at.desc()).first()
    if not latest:
        return AnalysisResponse(
            consumption="暂无分析",
            investment="暂无分析",
            suggestion="点击分析按钮获取 AI 建议"
        )

    batch_time = latest.created_at
    analyses = db.query(AnalysisResult).filter(
        AnalysisResult.created_at == batch_time
    ).all()

    result = {}
    for a in analyses:
        result[a.analysis_type] = a.content

    return AnalysisResponse(
        consumption=result.get("consumption", "暂无分析"),
        investment=result.get("investment", "暂无分析"),
        suggestion=result.get("suggestion", "暂无建议")
    )


@app.get("/analysis/history")
async def get_analysis_history(limit: int = 20, db: Session = Depends(get_db)):
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


# ===== 调度器状态 =====

@app.get("/scheduler/status")
async def scheduler_status():
    """获取调度器状态"""
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None
        })
    return {"running": _scheduler.running, "jobs": jobs}


@app.post("/scheduler/trigger/{job_id}")
async def trigger_job(job_id: str):
    """手动触发定时任务"""
    from .scheduler import cleanup_old_notifications, scheduled_daily_analysis
    job_map = {
        "cleanup_notifications": cleanup_old_notifications,
        "daily_analysis": scheduled_daily_analysis
    }
    if job_id not in job_map:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")
    await job_map[job_id]()
    return {"message": f"已触发任务 {job_id}"}


# ===== 资产管理 =====

@app.get("/assets", response_model=List[AssetResponse])
async def list_assets(
    asset_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取资产列表"""
    query = db.query(Asset)
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if status:
        query = query.filter(Asset.status == status)
    return query.order_by(Asset.updated_at.desc()).all()


@app.post("/assets", response_model=AssetResponse)
async def create_asset(asset: AssetCreate, db: Session = Depends(get_db)):
    """添加资产"""
    db_asset = Asset(**asset.model_dump())
    db.add(db_asset)
    db.commit()
    db.refresh(db_asset)
    return db_asset


@app.put("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: int,
    asset_update: AssetUpdate,
    db: Session = Depends(get_db)
):
    """更新资产"""
    db_asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not db_asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    
    update_data = asset_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_asset, key, value)
    db_asset.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_asset)
    return db_asset


@app.delete("/assets/{asset_id}")
async def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    """删除资产"""
    db_asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not db_asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    db.delete(db_asset)
    db.commit()
    return {"message": "已删除"}


# ===== 负债管理 =====

@app.get("/liabilities", response_model=List[LiabilityResponse])
async def list_liabilities(
    liability_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取负债列表"""
    query = db.query(Liability)
    if liability_type:
        query = query.filter(Liability.liability_type == liability_type)
    if status:
        query = query.filter(Liability.status == status)
    return query.order_by(Liability.updated_at.desc()).all()


@app.post("/liabilities", response_model=LiabilityResponse)
async def create_liability(liability: LiabilityCreate, db: Session = Depends(get_db)):
    """添加负债"""
    db_liability = Liability(**liability.model_dump())
    db.add(db_liability)
    db.commit()
    db.refresh(db_liability)
    return db_liability


@app.put("/liabilities/{liability_id}", response_model=LiabilityResponse)
async def update_liability(
    liability_id: int,
    liability_update: LiabilityUpdate,
    db: Session = Depends(get_db)
):
    """更新负债"""
    db_liability = db.query(Liability).filter(Liability.id == liability_id).first()
    if not db_liability:
        raise HTTPException(status_code=404, detail="负债不存在")
    
    update_data = liability_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_liability, key, value)
    db_liability.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_liability)
    return db_liability


@app.delete("/liabilities/{liability_id}")
async def delete_liability(liability_id: int, db: Session = Depends(get_db)):
    """删除负债"""
    db_liability = db.query(Liability).filter(Liability.id == liability_id).first()
    if not db_liability:
        raise HTTPException(status_code=404, detail="负债不存在")
    db.delete(db_liability)
    db.commit()
    return {"message": "已删除"}


# ===== 设置 =====

@app.get("/settings")
async def get_settings(db: Session = Depends(get_db)):
    """获取所有设置"""
    settings = db.query(Setting).all()
    return {s.key: s.value for s in settings}


@app.put("/settings")
async def update_settings(items: dict, db: Session = Depends(get_db)):
    """批量更新设置"""
    for key, value in items.items():
        existing = db.query(Setting).filter(Setting.key == key).first()
        if existing:
            existing.value = str(value)
        else:
            db.add(Setting(key=key, value=str(value)))
    db.commit()
    return {"status": "ok", "updated": len(items)}


@app.get("/settings/sources")
async def get_sources(db: Session = Depends(get_db)):
    """获取通知源配置"""
    raw = db.query(Setting).filter(Setting.key == "notification_sources").first()
    if not raw or not raw.value:
        # 默认全部开启
        return {"cmb": True, "icbc": True, "ccb": True, "alipay": True, "wechat_pay": True}
    import json
    return json.loads(raw.value)


@app.put("/settings/sources")
async def update_sources(sources: dict, db: Session = Depends(get_db)):
    """更新通知源配置"""
    import json
    existing = db.query(Setting).filter(Setting.key == "notification_sources").first()
    if existing:
        existing.value = json.dumps(sources)
    else:
        db.add(Setting(key="notification_sources", value=json.dumps(sources)))
    db.commit()
    return {"status": "ok"}


@app.get("/settings/agents")
async def get_agent_configs(db: Session = Depends(get_db)):
    """获取 Agent 配置"""
    agents = db.query(AgentConfig).all()
    return [{
        "id": a.id, "name": a.name, "api_endpoint": a.api_endpoint,
        "is_active": a.is_active, "system_prompt": a.system_prompt or ""
    } for a in agents]


@app.put("/settings/agents/{agent_id}")
async def update_agent_config(agent_id: int, data: dict, db: Session = Depends(get_db)):
    """更新 Agent 配置"""
    agent = db.query(AgentConfig).filter(AgentConfig.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if "is_active" in data:
        agent.is_active = data["is_active"]
    if "name" in data:
        agent.name = data["name"]
    if "api_endpoint" in data:
        agent.api_endpoint = data["api_endpoint"]
    if "system_prompt" in data:
        agent.system_prompt = data["system_prompt"]
    db.commit()
    return {"status": "ok"}
