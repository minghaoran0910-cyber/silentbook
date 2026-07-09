from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
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

# CORS - 开发环境允许所有，生产环境需要配置
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5000")
PARSER_API_URL = os.getenv("PARSER_API_URL", "http://localhost:6000")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    yield
    # Shutdown (if needed)

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
                "confidence": db_tx.confidence
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
