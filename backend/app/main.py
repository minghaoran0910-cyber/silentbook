from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from .database import get_db, SessionLocal, Transaction, AnalysisResult, Asset, Liability, AgentConfig, Setting, User, Account, Transfer, init_db
from .schemas import (
    TransactionCreate, TransactionUpdate, TransactionResponse,
    AnalysisResponse, DashboardStats,
    AssetCreate, AssetUpdate, AssetResponse,
    LiabilityCreate, LiabilityUpdate, LiabilityResponse,
    AccountCreate, AccountUpdate, AccountResponse, AccountTransfer, TransferResponse
)
from .auth import router as auth_router
import httpx
import os
import logging
import time
import collections
from .scheduler import create_scheduler
from .notification_push import pusher

# CORS - 开发环境允许所有，生产环境需要配置
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5000")
PARSER_API_URL = os.getenv("PARSER_API_URL", "http://localhost:6000")

# ===== API 限流配置 =====
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds
_request_log = collections.defaultdict(collections.deque)


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

# 注册认证路由
app.include_router(auth_router)

# ===== API 限流中间件 =====
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    if request.url.path in ["/health", "/"]:
        return await call_next(request)
    
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
            
            # 实时推送到微信/飞书
            push_result = await pusher.push_transaction({
                "amount": db_tx.amount,
                "category": db_tx.category,
                "account": db_tx.account,
                "transaction_type": db_tx.transaction_type,
                "description": db_tx.description,
                "parsed_at": db_tx.parsed_at
            })
            
            return {
                "status": "created",
                "id": db_tx.id,
                "amount": db_tx.amount,
                "category": db_tx.category,
                "type": db_tx.transaction_type,
                "confidence": db_tx.confidence,
                "push_result": push_result,
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

# ===== 预算三级分类 =====
# L1 必要支出（房租/水电/餐饮/交通）— <10% 可压缩
# L2 改善支出（健身/学习/社交）— 30-50% 可压缩
# L3 非必要支出（娱乐/奢侈品）— 80-100% 可砍

BUDGET_LEVELS = {"L1", "L2", "L3"}

# ===== 五级预警阈值 (V2-007) =====
# 五级预警：安全/正常/提醒/超支/严重超支
# 每级定义：级别、名称、颜色、usage上界（小数）
ALERT_LEVELS = [
    {"level": 1, "name": "安全",     "color": "green",  "max": 0.5},
    {"level": 2, "name": "正常",     "color": "blue",   "max": 0.8},
    {"level": 3, "name": "提醒",     "color": "yellow", "max": 1.0},
    {"level": 4, "name": "超支",     "color": "orange", "max": 1.2},
    {"level": 5, "name": "严重超支", "color": "red",    "max": float('inf')},
]

# 默认预警阈值列表（可被预算级自定义覆盖）
DEFAULT_ALERT_THRESHOLDS = [0.5, 0.8, 1.0, 1.2]


def get_alert_level(usage_rate: float, custom_thresholds: list = None) -> dict:
    """根据使用率返回预警级别。usage_rate 是小数（0.85 = 85%）。"""
    thresholds = custom_thresholds if custom_thresholds and len(custom_thresholds) == 4 else DEFAULT_ALERT_THRESHOLDS
    for i, t in enumerate(thresholds):
        if usage_rate < t:
            return ALERT_LEVELS[i]
    return ALERT_LEVELS[4]


LEVEL_LABELS = {
    "L1": "必要支出",
    "L2": "改善支出",
    "L3": "非必要支出",
}

LEVEL_COMPRESSIBILITY = {
    "L1": "<10%",
    "L2": "30-50%",
    "L3": "80-100%",
}

# 默认分类→级别映射（用户可覆盖）
DEFAULT_CATEGORY_LEVELS = {
    # L1 必要
    "房租": "L1", "水电": "L1", "燃气": "L1", "物业": "L1",
    "餐饮": "L1", "主食": "L1", "买菜": "L1", "外卖": "L1",
    "交通": "L1", "地铁": "L1", "公交": "L1", "打车": "L1", "停车": "L1",
    "话费": "L1", "网费": "L1", "保险": "L1", "医疗": "L1",
    "日用": "L1", "母婴": "L1",
    # L2 改善
    "健身": "L2", "学习": "L2", "课程": "L2", "书籍": "L2",
    "社交": "L2", "聚餐": "L2", "礼物": "L2", "理发": "L2",
    "咖啡": "L2", "水果": "L2", "零食": "L2",
    "订阅": "L2", "会员": "L2", "软件": "L2",
    # L3 非必要
    "娱乐": "L3", "游戏": "L3", "电影": "L3", "演出": "L3",
    "购物": "L3", "服饰": "L3", "电子": "L3", "数码": "L3",
    "旅游": "L3", "酒店": "L3", "机票": "L3",
    "彩票": "L3", "赌博": "L3",
}

def get_category_level(category: str, db) -> str:
    """获取分类对应的预算级别：优先查预算配置，其次用默认映射，默认L2"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if raw and raw.value:
        budgets = json.loads(raw.value)
        for b in budgets:
            if b.get("category") == category and "level" in b:
                return b["level"]
    return DEFAULT_CATEGORY_LEVELS.get(category, "L2")


class BudgetCreate(BaseModel):
    category: str
    monthly_limit: float
    alert_threshold: float = 0.8  # 向后兼容，单个阈值
    level: str = Field("L2", pattern="^(L1|L2|L3)$")
    alert_thresholds: Optional[List[float]] = None  # 五级预警自定义阈值（4个上界值）

class BudgetResponse(BaseModel):
    id: int
    category: str
    monthly_limit: float
    alert_threshold: float
    level: str
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
        custom_ts = b.get("alert_thresholds")
        alert_info = get_alert_level(usage, custom_ts)
        result.append({
            **b,
            "current_spent": round(float(spent), 2),
            "usage_rate": round(usage * 100, 1),
            "alert": usage >= b.get("alert_threshold", 0.8),
            "alert_level": alert_info["level"],
            "alert_name": alert_info["name"],
            "alert_color": alert_info["color"],
        })
    return result


@app.get("/budgets/levels")
async def get_budgets_by_level(db: Session = Depends(get_db)):
    """三级分类预算汇总：L1必要/L2改善/L3非必要"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    budgets = json.loads(raw.value) if raw and raw.value else []
    
    # 补全 level 字段（兼容旧数据）
    for b in budgets:
        if "level" not in b:
            b["level"] = DEFAULT_CATEGORY_LEVELS.get(b.get("category", ""), "L2")
    
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # 查本月所有支出
    month_txs = db.query(Transaction).filter(
        Transaction.transaction_type == "expense",
        Transaction.parsed_at >= month_start
    ).all()
    
    # 按分类汇总实际支出
    actual_by_category = {}
    for tx in month_txs:
        cat = tx.category or "其他"
        actual_by_category[cat] = actual_by_category.get(cat, 0) + tx.amount
    
    levels_data = {}
    for level in ["L1", "L2", "L3"]:
        level_budgets = [b for b in budgets if b.get("level") == level]
        budget_total = sum(b["monthly_limit"] for b in level_budgets)
        
        # 已设预算分类的支出
        budgeted_spent = 0
        items = []
        for b in level_budgets:
            spent = actual_by_category.get(b["category"], 0)
            budgeted_spent += spent
            usage = spent / b["monthly_limit"] if b["monthly_limit"] > 0 else 0
            alert_info = get_alert_level(usage, b.get("alert_thresholds"))
            items.append({
                "category": b["category"],
                "monthly_limit": b["monthly_limit"],
                "current_spent": round(spent, 2),
                "usage_rate": round(usage * 100, 1),
                "alert_threshold": b.get("alert_threshold", 0.8),
                "alert": usage >= b.get("alert_threshold", 0.8),
                "alert_level": alert_info["level"],
                "alert_name": alert_info["name"],
                "alert_color": alert_info["color"],
            })
        
        # 未设预算但属于该级别的分类支出
        budgeted_cats = {b["category"] for b in level_budgets}
        unbudgeted_spent = 0
        for cat, amt in actual_by_category.items():
            if cat not in budgeted_cats:
                cat_level = DEFAULT_CATEGORY_LEVELS.get(cat, "L2")
                if cat_level == level:
                    unbudgeted_spent += amt
        
        total_spent = budgeted_spent + unbudgeted_spent
        levels_data[level] = {
            "label": LEVEL_LABELS[level],
            "compressibility": LEVEL_COMPRESSIBILITY[level],
            "budget_total": round(budget_total, 2),
            "spent_total": round(total_spent, 2),
            "budgeted_spent": round(budgeted_spent, 2),
            "unbudgeted_spent": round(unbudgeted_spent, 2),
            "usage_rate": round(total_spent / budget_total * 100, 1) if budget_total > 0 else 0,
            "items": items,
        }
    
    return {
        "total_budget": round(sum(b["monthly_limit"] for b in budgets), 2),
        "total_spent": round(sum(v["spent_total"] for v in levels_data.values()), 2),
        "levels": levels_data,
    }


@app.get("/budgets/alerts")
async def get_budget_alerts(db: Session = Depends(get_db)):
    """五级预警状态：返回每个预算的预警级别"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if not raw or not raw.value:
        return {"alerts": [], "summary": {"safe": 0, "normal": 0, "notice": 0, "over": 0, "critical": 0}}

    budgets = json.loads(raw.value)
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    alerts = []
    summary = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for b in budgets:
        spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.category == b["category"],
            Transaction.transaction_type == "expense",
            Transaction.parsed_at >= month_start
        ).scalar() or 0.0

        usage = float(spent) / b["monthly_limit"] if b["monthly_limit"] > 0 else 0
        alert_info = get_alert_level(usage, b.get("alert_thresholds"))
        summary[alert_info["level"]] += 1
        alerts.append({
            "category": b["category"],
            "monthly_limit": b["monthly_limit"],
            "current_spent": round(float(spent), 2),
            "usage_rate": round(usage * 100, 1),
            "alert_level": alert_info["level"],
            "alert_name": alert_info["name"],
            "alert_color": alert_info["color"],
            "level": b.get("level", DEFAULT_CATEGORY_LEVELS.get(b.get("category", ""), "L2")),
        })

    return {
        "alerts": alerts,
        "summary": {
            "safe": summary[1],
            "normal": summary[2],
            "notice": summary[3],
            "over": summary[4],
            "critical": summary[5],
        },
    }


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
        if budget.alert_thresholds:
            existing["alert_thresholds"] = budget.alert_thresholds
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


# ===== 预算模板（V2-008）=====
# 三套预设模板：节俭型/均衡型/宽松型
# 每套模板包含 L1/L2/L3 三级分类的月度预算

BUDGET_TEMPLATES = {
    "frugal": {
        "name": "节俭型",
        "description": "必要支出为主，压缩改善和非必要支出",
        "monthly_total": 4750,
        "budgets": [
            # L1 必要支出
            {"category": "房租", "monthly_limit": 2500, "level": "L1", "alert_threshold": 0.9},
            {"category": "餐饮", "monthly_limit": 1000, "level": "L1", "alert_threshold": 0.9},
            {"category": "交通", "monthly_limit": 200, "level": "L1", "alert_threshold": 0.9},
            {"category": "水电", "monthly_limit": 150, "level": "L1", "alert_threshold": 0.9},
            {"category": "话费", "monthly_limit": 50, "level": "L1", "alert_threshold": 0.9},
            {"category": "日用", "monthly_limit": 150, "level": "L1", "alert_threshold": 0.9},
            # L2 改善支出
            {"category": "学习", "monthly_limit": 200, "level": "L2", "alert_threshold": 0.8},
            {"category": "社交", "monthly_limit": 100, "level": "L2", "alert_threshold": 0.8},
            # L3 非必要支出
            {"category": "娱乐", "monthly_limit": 100, "level": "L3", "alert_threshold": 0.8},
            {"category": "购物", "monthly_limit": 300, "level": "L3", "alert_threshold": 0.8},
        ],
    },
    "balanced": {
        "name": "均衡型",
        "description": "必要支出充裕，改善支出合理，适度非必要支出",
        "monthly_total": 8400,
        "budgets": [
            # L1 必要支出
            {"category": "房租", "monthly_limit": 3500, "level": "L1", "alert_threshold": 0.9},
            {"category": "餐饮", "monthly_limit": 2000, "level": "L1", "alert_threshold": 0.9},
            {"category": "交通", "monthly_limit": 400, "level": "L1", "alert_threshold": 0.9},
            {"category": "水电", "monthly_limit": 300, "level": "L1", "alert_threshold": 0.9},
            {"category": "话费", "monthly_limit": 100, "level": "L1", "alert_threshold": 0.9},
            {"category": "日用", "monthly_limit": 300, "level": "L1", "alert_threshold": 0.9},
            # L2 改善支出
            {"category": "健身", "monthly_limit": 300, "level": "L2", "alert_threshold": 0.8},
            {"category": "学习", "monthly_limit": 300, "level": "L2", "alert_threshold": 0.8},
            {"category": "社交", "monthly_limit": 300, "level": "L2", "alert_threshold": 0.8},
            {"category": "咖啡", "monthly_limit": 200, "level": "L2", "alert_threshold": 0.8},
            # L3 非必要支出
            {"category": "娱乐", "monthly_limit": 200, "level": "L3", "alert_threshold": 0.8},
            {"category": "购物", "monthly_limit": 300, "level": "L3", "alert_threshold": 0.8},
            {"category": "旅游", "monthly_limit": 200, "level": "L3", "alert_threshold": 0.8},
        ],
    },
    "loose": {
        "name": "宽松型",
        "description": "各层级充裕，不刻意压缩非必要支出",
        "monthly_total": 14300,
        "budgets": [
            # L1 必要支出
            {"category": "房租", "monthly_limit": 5000, "level": "L1", "alert_threshold": 0.9},
            {"category": "餐饮", "monthly_limit": 3500, "level": "L1", "alert_threshold": 0.9},
            {"category": "交通", "monthly_limit": 800, "level": "L1", "alert_threshold": 0.9},
            {"category": "水电", "monthly_limit": 500, "level": "L1", "alert_threshold": 0.9},
            {"category": "话费", "monthly_limit": 200, "level": "L1", "alert_threshold": 0.9},
            {"category": "日用", "monthly_limit": 500, "level": "L1", "alert_threshold": 0.9},
            # L2 改善支出
            {"category": "健身", "monthly_limit": 500, "level": "L2", "alert_threshold": 0.8},
            {"category": "学习", "monthly_limit": 500, "level": "L2", "alert_threshold": 0.8},
            {"category": "社交", "monthly_limit": 500, "level": "L2", "alert_threshold": 0.8},
            {"category": "咖啡", "monthly_limit": 500, "level": "L2", "alert_threshold": 0.8},
            # L3 非必要支出
            {"category": "娱乐", "monthly_limit": 500, "level": "L3", "alert_threshold": 0.8},
            {"category": "购物", "monthly_limit": 800, "level": "L3", "alert_threshold": 0.8},
            {"category": "旅游", "monthly_limit": 500, "level": "L3", "alert_threshold": 0.8},
        ],
    },
}


@app.get("/budgets/templates")
async def list_budget_templates():
    """列出所有预算模板"""
    result = []
    for key, tpl in BUDGET_TEMPLATES.items():
        level_summary = {"L1": 0, "L2": 0, "L3": 0}
        for b in tpl["budgets"]:
            level_summary[b["level"]] += b["monthly_limit"]
        result.append({
            "key": key,
            "name": tpl["name"],
            "description": tpl["description"],
            "monthly_total": tpl["monthly_total"],
            "category_count": len(tpl["budgets"]),
            "level_summary": level_summary,
        })
    return result


@app.get("/budgets/templates/{template_key}")
async def get_budget_template(template_key: str):
    """获取某个预算模板的详情"""
    if template_key not in BUDGET_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"模板 '{template_key}' 不存在，可选: {', '.join(BUDGET_TEMPLATES.keys())}")
    tpl = BUDGET_TEMPLATES[template_key]
    return {
        "key": template_key,
        "name": tpl["name"],
        "description": tpl["description"],
        "monthly_total": tpl["monthly_total"],
        "budgets": tpl["budgets"],
    }


@app.post("/budgets/templates/{template_key}/apply")
async def apply_budget_template(template_key: str, db: Session = Depends(get_db)):
    """应用预算模板 — 替换现有所有预算"""
    import json
    if template_key not in BUDGET_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"模板 '{template_key}' 不存在，可选: {', '.join(BUDGET_TEMPLATES.keys())}")

    tpl = BUDGET_TEMPLATES[template_key]
    budgets_data = [b.copy() for b in tpl["budgets"]]
    # 补全 alert_thresholds 为 None（使用默认五级预警）
    for b in budgets_data:
        b.setdefault("alert_thresholds", None)

    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if raw:
        raw.value = json.dumps(budgets_data)
    else:
        db.add(Setting(key="budgets", value=json.dumps(budgets_data)))
    db.commit()

    return {
        "status": "ok",
        "template": template_key,
        "template_name": tpl["name"],
        "applied_count": len(budgets_data),
        "monthly_total": tpl["monthly_total"],
        "budgets": budgets_data,
    }


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


@app.get("/auth/status")
async def get_auth_status(db: Session = Depends(get_db)):
    """获取认证状态"""
    stored = db.query(Setting).filter(Setting.key == "auth_password").first()
    return {"auth_enabled": bool(stored)}


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


# ===== 多账户管理（四账户体系） =====

@app.get("/accounts", response_model=List[AccountResponse])
async def list_accounts(
    purpose: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取账户列表"""
    query = db.query(Account)
    if purpose:
        query = query.filter(Account.purpose == purpose)
    if status:
        query = query.filter(Account.status == status)
    return query.order_by(Account.updated_at.desc()).all()


@app.post("/accounts", response_model=AccountResponse)
async def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    """创建账户"""
    db_account = Account(**account.model_dump())
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account


@app.get("/accounts/summary")
async def get_accounts_summary(db: Session = Depends(get_db)):
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


@app.get("/accounts/transfers", response_model=List[TransferResponse])
async def list_transfers(
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db)
):
    """获取转账历史列表"""
    query = db.query(Transfer)
    if account_id:
        query = query.filter(
            (Transfer.from_account_id == account_id) | (Transfer.to_account_id == account_id)
        )
    return query.order_by(Transfer.created_at.desc()).offset(skip).limit(limit).all()


@app.get("/accounts/transfers/{transfer_id}", response_model=TransferResponse)
async def get_transfer(transfer_id: int, db: Session = Depends(get_db)):
    """获取单条转账记录"""
    transfer = db.query(Transfer).filter(Transfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="转账记录不存在")
    return transfer


@app.get("/accounts/{account_id}", response_model=AccountResponse)
async def get_account(account_id: int, db: Session = Depends(get_db)):
    """获取单个账户"""
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")
    return account


@app.put("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    account_update: AccountUpdate,
    db: Session = Depends(get_db)
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


@app.delete("/accounts/{account_id}")
async def delete_account(account_id: int, db: Session = Depends(get_db)):
    """删除账户"""
    db_account = db.query(Account).filter(Account.id == account_id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="账户不存在")
    db.delete(db_account)
    db.commit()
    return {"message": "已删除"}


@app.post("/accounts/transfer")
async def transfer_between_accounts(transfer: AccountTransfer, db: Session = Depends(get_db)):
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


# ===== 负债清单增强（V2-011）=====

# 负债类型中文标签
LIABILITY_TYPE_LABELS = {
    "mortgage": "房贷",
    "car_loan": "车贷",
    "credit_card": "信用卡",
    "credit_card_installment": "信用卡分期",
    "huabei": "花呗",
    "baitiao": "白条",
    "loan": "其他贷款",
    "other": "其他",
}

# 负债类型默认优先级排序
LIABILITY_TYPE_ORDER = [
    "mortgage", "car_loan", "credit_card", "credit_card_installment",
    "huabei", "baitiao", "loan", "other"
]


@app.get("/liabilities/summary")
async def get_liabilities_summary(db: Session = Depends(get_db)):
    """负债清单汇总：按类型分组统计 + 总体概览"""
    liabilities = db.query(Liability).all()
    
    # 按类型分组
    by_type = {}
    for lt in LIABILITY_TYPE_ORDER:
        by_type[lt] = {
            "label": LIABILITY_TYPE_LABELS[lt],
            "items": [],
            "total_amount": 0,
            "current_amount": 0,
            "monthly_payment": 0,
            "count": 0,
            "active_count": 0,
        }
    
    total_current = 0
    total_monthly_payment = 0
    total_interest_estimate = 0
    status_counts = {"active": 0, "paid": 0, "overdue": 0}
    
    for liab in liabilities:
        lt = liab.liability_type if liab.liability_type in by_type else "other"
        entry = by_type[lt]
        entry["items"].append({
            "id": liab.id,
            "name": liab.name,
            "total_amount": liab.total_amount,
            "current_amount": liab.current_amount,
            "interest_rate": liab.interest_rate,
            "monthly_payment": liab.monthly_payment,
            "remaining_periods": liab.remaining_periods,
            "due_date": str(liab.due_date) if liab.due_date else None,
            "status": liab.status,
            "notes": liab.notes,
        })
        entry["total_amount"] += liab.total_amount
        entry["current_amount"] += liab.current_amount
        entry["monthly_payment"] += liab.monthly_payment or 0
        entry["count"] += 1
        if liab.status == "active":
            entry["active_count"] += 1
        
        total_current += liab.current_amount
        total_monthly_payment += liab.monthly_payment or 0
        # 估算总利息 = 月供 × 剩余期数 - 当前待还
        if liab.monthly_payment and liab.remaining_periods:
            total_interest_estimate += liab.monthly_payment * liab.remaining_periods - liab.current_amount
        
        if liab.status in status_counts:
            status_counts[liab.status] += 1
    
    # 清除空类型
    by_type = {k: v for k, v in by_type.items() if v["count"] > 0}
    
    return {
        "total_current_amount": round(total_current, 2),
        "total_monthly_payment": round(total_monthly_payment, 2),
        "total_interest_estimate": round(max(total_interest_estimate, 0), 2),
        "status_counts": status_counts,
        "total_count": len(liabilities),
        "by_type": by_type,
    }


@app.get("/liabilities/debt-ratio")
async def get_debt_ratio(db: Session = Depends(get_db)):
    """负债率监控：月还款额 / 月收入，超过 40% 预警"""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # 本月收入
    monthly_income = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.transaction_type == "income",
        Transaction.parsed_at >= month_start
    ).scalar() or 0.0
    
    # 活跃负债的月供总额
    active_liabilities = db.query(Liability).filter(Liability.status == "active").all()
    total_monthly_payment = sum(l.monthly_payment or 0 for l in active_liabilities)
    total_current_amount = sum(l.current_amount for l in active_liabilities)
    
    # 计算负债率
    debt_ratio = (total_monthly_payment / monthly_income * 100) if monthly_income > 0 else 0
    
    # 预警级别
    DEBT_RATIO_THRESHOLD = 40  # 40% 预警线
    if monthly_income == 0:
        alert_level = "unknown"
        alert_message = "本月无收入数据，无法计算负债率"
    elif debt_ratio < 30:
        alert_level = "safe"
        alert_message = "负债率健康"
    elif debt_ratio < DEBT_RATIO_THRESHOLD:
        alert_level = "notice"
        alert_message = "负债率偏高，建议关注"
    elif debt_ratio < 60:
        alert_level = "warning"
        alert_message = "负债率超过 40% 预警线，建议优化债务结构"
    else:
        alert_level = "critical"
        alert_message = "负债率严重过高，存在财务风险"
    
    # 按类型分组的月供
    by_type = {}
    for l in active_liabilities:
        lt = LIABILITY_TYPE_LABELS.get(l.liability_type, l.liability_type)
        if lt not in by_type:
            by_type[lt] = {"monthly_payment": 0, "current_amount": 0, "count": 0}
        by_type[lt]["monthly_payment"] += l.monthly_payment or 0
        by_type[lt]["current_amount"] += l.current_amount
        by_type[lt]["count"] += 1
    
    return {
        "monthly_income": round(monthly_income, 2),
        "total_monthly_payment": round(total_monthly_payment, 2),
        "total_current_debt": round(total_current_amount, 2),
        "debt_ratio": round(debt_ratio, 1),
        "threshold": DEBT_RATIO_THRESHOLD,
        "alert_level": alert_level,
        "alert_message": alert_message,
        "is_over_threshold": debt_ratio >= DEBT_RATIO_THRESHOLD,
        "by_type": {k: {**v, "monthly_payment": round(v["monthly_payment"], 2), "current_amount": round(v["current_amount"], 2)} for k, v in by_type.items()},
        "active_liability_count": len(active_liabilities),
    }


# ===== 还款计划（V2-012）=====

def _add_months(dt: datetime, months: int) -> datetime:
    """简单月份加法，不依赖 dateutil"""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, 28)  # 避免月末溢出
    return dt.replace(year=year, month=month, day=day)


@app.get("/liabilities/{liability_id}/repayment-plan")
async def get_repayment_plan(liability_id: int, db: Session = Depends(get_db)):
    """还款计划：每期金额/利息/本金/余额 + 总利息 + 预计还清日期"""
    liability = db.query(Liability).filter(Liability.id == liability_id).first()
    if not liability:
        raise HTTPException(status_code=404, detail="负债不存在")
    if liability.status == "paid":
        return {"schedule": [], "total_interest": 0, "total_payment": 0,
                "remaining_periods": 0, "payoff_date": None, "message": "该负债已还清"}
    
    current = liability.current_amount or 0
    monthly_payment = liability.monthly_payment or 0
    remaining_periods = liability.remaining_periods or 0
    monthly_rate = (liability.interest_rate or 0) / 12 / 100
    
    if current <= 0 or remaining_periods <= 0 or monthly_payment <= 0:
        return {"schedule": [], "total_interest": 0, "total_payment": 0,
                "remaining_periods": 0, "payoff_date": None,
                "message": "当前余额、月供或剩余期数为0，无法生成还款计划"}
    
    # 检查月供是否足以覆盖首月利息
    first_month_interest = current * monthly_rate
    if monthly_payment <= first_month_interest and monthly_rate > 0:
        return {"error": "月供不足以覆盖月利息，无法生成还款计划",
                "monthly_payment": monthly_payment,
                "first_month_interest": round(first_month_interest, 2)}
    
    schedule = []
    total_interest = 0.0
    total_payment = 0.0
    balance = current
    
    for period in range(1, remaining_periods + 1):
        interest = round(balance * monthly_rate, 2)
        principal = round(monthly_payment - interest, 2)
        
        # 最后一期或余额不足以支撑完整月供：清零余额
        if period == remaining_periods or principal >= balance:
            principal = round(balance, 2)
            payment = round(principal + interest, 2)
        else:
            payment = round(monthly_payment, 2)
        
        balance = round(balance - principal, 2)
        total_interest += interest
        total_payment += payment
        
        schedule.append({
            "period": period,
            "payment": payment,
            "principal": principal,
            "interest": interest,
            "balance": max(balance, 0),
            "date": _add_months(datetime.utcnow(), period).strftime("%Y-%m-%d"),
        })
        
        if balance <= 0:
            break
    
    payoff_date = _add_months(datetime.utcnow(), len(schedule)).strftime("%Y-%m-%d")
    
    return {
        "liability_id": liability_id,
        "liability_name": liability.name,
        "liability_type": liability.liability_type,
        "schedule": schedule,
        "total_interest": round(total_interest, 2),
        "total_payment": round(total_payment, 2),
        "total_principal": round(current, 2),
        "remaining_periods": len(schedule),
        "monthly_payment": monthly_payment,
        "current_amount": current,
        "annual_interest_rate": liability.interest_rate or 0,
        "payoff_date": payoff_date,
    }


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


# ===== 现金流日历（V2-009）=====

@app.get("/cashflow/calendar")
async def get_cashflow_calendar(
    year: Optional[int] = None,
    month: Optional[int] = None,
    account: Optional[str] = None,
    db: Session = Depends(get_db)
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

@app.get("/cashflow/forecast")
async def get_cashflow_forecast(
    days: int = 30,
    history_days: int = 90,
    account: Optional[str] = None,
    db: Session = Depends(get_db)
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


# ===== 基础报表（V2-013）=====

@app.get("/reports/monthly-summary")
async def get_monthly_summary(year: int = None, month: int = None, db: Session = Depends(get_db)):
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

@app.get("/reports/cashflow")
async def get_cashflow_report(
    year: int = None,
    month: int = None,
    account: Optional[str] = None,
    db: Session = Depends(get_db)
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


@app.get("/reports/balance-sheet")
async def get_balance_sheet(db: Session = Depends(get_db)):
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


@app.get("/reports/health-score")
async def get_health_score(year: int = None, month: int = None, db: Session = Depends(get_db)):
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

@app.get("/investment/risk-profile")
async def get_risk_profile(year: int = None, month: int = None, db: Session = Depends(get_db)):
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


@app.get("/investment/allocation")
async def get_asset_allocation(db: Session = Depends(get_db)):
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

from .database import Position, TradeRecord
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


@app.get("/positions")
async def list_positions(status: str = "active", db: Session = Depends(get_db)):
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


@app.post("/positions")
async def create_position(pos: PositionCreate, db: Session = Depends(get_db)):
    """创建持仓"""
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
    db.commit()
    db.refresh(position)
    return {"id": position.id, "name": position.name, "message": "持仓创建成功"}


@app.put("/positions/{position_id}")
async def update_position(position_id: int, pos: PositionUpdate, db: Session = Depends(get_db)):
    """更新持仓（修改当前价格等）"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="持仓不存在")

    for field, value in pos.model_dump(exclude_unset=True).items():
        setattr(position, field, value)
    position.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "持仓更新成功", "id": position_id}


@app.delete("/positions/{position_id}")
async def close_position(position_id: int, db: Session = Depends(get_db)):
    """关闭持仓（标记为 closed）"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="持仓不存在")
    position.status = "closed"
    position.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "持仓已关闭", "id": position_id}


@app.post("/positions/trades")
async def add_trade(trade: TradeRecordCreate, db: Session = Depends(get_db)):
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
    db.commit()

    return {
        "message": f"交易记录已添加（{trade.trade_type}）",
        "position_id": trade.position_id,
        "remaining_quantity": position.quantity,
    }


@app.get("/positions/{position_id}/trades")
async def get_position_trades(position_id: int, db: Session = Depends(get_db)):
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


@app.get("/investment/returns")
async def get_investment_returns(position_id: int = None, db: Session = Depends(get_db)):
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
