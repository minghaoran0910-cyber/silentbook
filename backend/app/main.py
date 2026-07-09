from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timedelta
from .database import get_db, SessionLocal, Transaction, AnalysisResult, Asset, Liability, init_db
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
