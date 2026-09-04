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
    get_alert_level, get_category_level, normalize_account_name,
)

router = APIRouter()

logger = logging.getLogger("silentbook")

@router.get("/export/csv")
async def export_csv(user: User = Depends(require_user), db: Session = Depends(get_db)):
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


@router.post("/import/csv")
async def import_csv(file: dict, user: User = Depends(require_user), db: Session = Depends(get_db)):
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
                account=normalize_account_name(row.get("账户", "")),
                description=row.get("描述", ""),
                transaction_type=row.get("类型", "expense"),
                confidence=float(row.get("置信度", 1.0)),
                parsed_at=datetime.utcnow()
            )
            db.add(tx)
            db.flush()  # 先落行再联动余额，保证账户存在时余额守恒
            _update_account_balance(db, tx.account, tx.transaction_type, tx.amount)
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


@router.post("/import/pdf")
async def import_pdf_endpoint(
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    """导入银行 PDF 流水（当前支持招商银行标准格式）"""
    from ..pdf_parser import parse_pdf
    
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="请上传 PDF 文件")
    
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(status_code=400, detail="文件过大，最大支持 20MB")
    
    try:
        result = parse_pdf(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 解析失败: {str(e)}")
    
    if not result['transactions']:
        return {
            "status": "warning",
            "message": "未能从 PDF 中解析出交易记录，请确认是银行标准格式流水",
            "bank": result['bank'],
            "total": 0
        }
    
    # 写入数据库
    imported = 0
    skipped = 0
    for tx_data in result['transactions']:
        if tx_data.get('amount', 0) <= 0:
            skipped += 1
            continue
        
        tx = Transaction(
            amount=tx_data['amount'],
            category=tx_data.get('category', '其他'),
            account=normalize_account_name(tx_data.get('account', '招商银行')),
            description=tx_data.get('description', ''),
            transaction_type=tx_data.get('transaction_type', 'expense'),
            raw_text=f"[PDF导入] {tx_data.get('date', '')} {tx_data.get('description', '')}",
            confidence=tx_data.get('confidence', 0.7),
            parsed_at=datetime.strptime(tx_data['date'], '%Y-%m-%d') if tx_data.get('date') else datetime.utcnow()
        )
        db.add(tx)
        db.flush()  # 先落行再联动余额，保证账户存在时余额守恒
        _update_account_balance(db, tx.account, tx.transaction_type, tx.amount)
        imported += 1
    
    db.commit()
    
    return {
        "status": "ok",
        "bank": result['bank'],
        "imported": imported,
        "skipped": skipped,
        "message": f"成功导入 {imported} 条交易记录"
    }


# ===== AI 配置（用户自定义模型） =====
