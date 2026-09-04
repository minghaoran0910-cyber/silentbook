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

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/tmp/silentbook-backups"))
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# 需要备份的表及其模型映射


BACKUP_TABLES = {
    "transactions": Transaction,
    "assets": Asset,
    "liabilities": Liability,
    "accounts": Account,
    "positions": Position,
    "trade_records": TradeRecord,
    "transfers": Transfer,
    "agent_configs": AgentConfig,
    "settings": Setting,
    "users": User,
}


def _serialize_row(row, model) -> dict:
    """将 ORM 对象序列化为 dict"""
    data = {}
    for col in model.__table__.columns:
        val = getattr(row, col.name, None)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        data[col.name] = val
    return data


def _get_last_checkpoint(db: Session, backup_type: str) -> Optional[datetime]:
    """获取上次成功备份的时间点"""
    last = db.query(BackupRecord).filter(
        BackupRecord.status == "completed",
        BackupRecord.backup_type == backup_type
    ).order_by(BackupRecord.created_at.desc()).first()
    if last and last.completed_at:
        return last.completed_at
    return None


def _backup_table_incremental(db: Session, model, since: Optional[datetime]) -> tuple:
    """增量备份单个表，返回 (所有记录, 新增数, 更新数)"""
    query = db.query(model)
    new_count = 0
    updated_count = 0

    if since:
        # 有 created_at 的表过滤新增
        if hasattr(model, 'created_at'):
            new_rows = query.filter(model.created_at > since).all()
            new_count = len(new_rows)
            updated_rows = []
            # 有 updated_at 的表过滤更新
            if hasattr(model, 'updated_at'):
                updated_rows = db.query(model).filter(
                    model.updated_at > since,
                    model.created_at <= since
                ).all()
                updated_count = len(updated_rows)
            # 合并
            all_ids = set()
            all_rows = []
            for r in new_rows + updated_rows:
                if r.id not in all_ids:
                    all_ids.add(r.id)
                    all_rows.append(r)
            return all_rows, new_count, updated_count
        else:
            # 没有时间戳字段，全量备份
            all_rows = query.all()
            return all_rows, len(all_rows), 0
    else:
        # 首次备份，全量
        all_rows = query.all()
        return all_rows, len(all_rows), 0


@router.post("/backup/create")
async def create_backup(
    backup_type: str = "incremental",
    tables: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """创建增量备份
    
    - backup_type: full(全量) 或 incremental(增量)
    - tables: 逗号分隔的表名，不传则备份全部
    """
    import time as _time
    start_time = _time.time()

    # 验证 backup_type
    if backup_type not in ("full", "incremental"):
        raise HTTPException(400, "backup_type 必须是 full 或 incremental")

    # 确定要备份的表
    if tables:
        table_names = [t.strip() for t in tables.split(",")]
        for t in table_names:
            if t not in BACKUP_TABLES:
                raise HTTPException(400, f"未知表名: {t}，可选: {list(BACKUP_TABLES.keys())}")
    else:
        table_names = list(BACKUP_TABLES.keys())

    # 获取上次备份时间点（增量模式）
    since = None
    if backup_type == "incremental":
        since = _get_last_checkpoint(db, "incremental")

    # 创建备份记录
    backup_record = BackupRecord(
        backup_type=backup_type,
        status="running",
        since_checkpoint=since,
        user_id=user.id,
    )
    db.add(backup_record)
    db.commit()
    db.refresh(backup_record)

    try:
        backup_data = {"metadata": {}, "tables": {}}
        table_details = {}
        total_records = 0

        for table_name in table_names:
            model = BACKUP_TABLES[table_name]
            if backup_type == "incremental" and since:
                rows, new_count, updated_count = _backup_table_incremental(db, model, since)
            else:
                rows = db.query(model).all()
                new_count = len(rows)
                updated_count = 0

            serialized = [_serialize_row(r, model) for r in rows]
            backup_data["tables"][table_name] = serialized
            table_details[table_name] = {
                "record_count": len(serialized),
                "new_records": new_count,
                "updated_records": updated_count,
            }
            total_records += len(serialized)

        backup_data["metadata"] = {
            "backup_id": backup_record.id,
            "backup_type": backup_type,
            "created_at": datetime.utcnow().isoformat(),
            "since_checkpoint": since.isoformat() if since else None,
            "table_count": len(table_names),
            "total_records": total_records,
        }

        # 写入压缩文件
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{backup_record.id}_{timestamp}.json.gz.enc"
        file_path = BACKUP_DIR / filename

        write_backup(file_path, backup_data)

        file_size = file_path.stat().st_size
        duration = _time.time() - start_time

        # 更新备份记录
        backup_record.status = "completed"
        backup_record.file_path = str(file_path)
        backup_record.file_size = file_size
        backup_record.record_count = total_records
        backup_record.tables_backed_up = json.dumps(table_details, ensure_ascii=False)
        backup_record.duration_seconds = round(duration, 2)
        backup_record.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(backup_record)

        return {
            "id": backup_record.id,
            "backup_type": backup_type,
            "status": "completed",
            "file_path": str(file_path),
            "file_size": file_size,
            "record_count": total_records,
            "duration_seconds": round(duration, 2),
            "tables": table_details,
            "since_checkpoint": since.isoformat() if since else None,
        }

    except Exception as e:
        backup_record.status = "failed"
        backup_record.error_message = str(e)
        backup_record.completed_at = datetime.utcnow()
        db.commit()
        raise HTTPException(500, f"备份失败: {str(e)}")


@router.get("/backup/list")
async def list_backups(
    limit: int = 20,
    status: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """列出备份记录"""
    query = db.query(BackupRecord).order_by(BackupRecord.created_at.desc())
    if status:
        query = query.filter(BackupRecord.status == status)
    records = query.limit(limit).all()

    return {
        "backups": [
            {
                "id": r.id,
                "backup_type": r.backup_type,
                "status": r.status,
                "file_path": r.file_path,
                "file_size": r.file_size,
                "record_count": r.record_count,
                "duration_seconds": r.duration_seconds,
                "since_checkpoint": r.since_checkpoint.isoformat() if r.since_checkpoint else None,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in records
        ],
        "total": db.query(BackupRecord).count(),
    }


@router.get("/backup/status")
async def get_backup_status(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取备份状态概览"""
    last = db.query(BackupRecord).filter(
        BackupRecord.status == "completed"
    ).order_by(BackupRecord.created_at.desc()).first()

    total_backups = db.query(BackupRecord).filter(
        BackupRecord.status == "completed"
    ).count()

    total_size = db.query(func.sum(BackupRecord.file_size)).filter(
        BackupRecord.status == "completed"
    ).scalar() or 0

    return {
        "last_backup": last.created_at.isoformat() if last and last.created_at else None,
        "last_backup_type": last.backup_type if last else None,
        "last_backup_status": last.status if last else None,
        "last_backup_records": last.record_count if last else 0,
        "total_backups": total_backups,
        "total_backup_size": total_size,
        "next_scheduled_backup": "每天 03:00 (Asia/Shanghai)",
        "backup_directory": str(BACKUP_DIR),
        "auto_backup_enabled": True,
    }


@router.get("/backup/{backup_id}")
async def get_backup_detail(backup_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取单个备份详情"""
    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if not record:
        raise HTTPException(404, "备份记录不存在")

    # 尝试读取备份文件内容预览
    preview = None
    if record.file_path and Path(record.file_path).exists():
        try:
            data = read_backup(Path(record.file_path))
            preview = {
                "metadata": data.get("metadata"),
                "table_names": list(data.get("tables", {}).keys()),
                "table_record_counts": {
                    t: len(rows) for t, rows in data.get("tables", {}).items()
                },
            }
        except Exception:
            preview = None

    return {
        "id": record.id,
        "backup_type": record.backup_type,
        "status": record.status,
        "file_path": record.file_path,
        "file_size": record.file_size,
        "record_count": record.record_count,
        "tables_backed_up": json.loads(record.tables_backed_up) if record.tables_backed_up else None,
        "since_checkpoint": record.since_checkpoint.isoformat() if record.since_checkpoint else None,
        "error_message": record.error_message,
        "duration_seconds": record.duration_seconds,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "preview": preview,
    }


@router.post("/backup/restore")
async def restore_backup(
    backup_id: int,
    tables: Optional[str] = None,
    dry_run: bool = True,
    confirmation: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """从备份恢复数据
    
    - dry_run=True 时只预览不实际恢复（默认）
    - tables: 逗号分隔的表名，不传则恢复全部
    """
    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if not record:
        raise HTTPException(404, "备份记录不存在")
    if record.status != "completed":
        raise HTTPException(400, "只能恢复已完成的备份")
    if not record.file_path or not Path(record.file_path).exists():
        raise HTTPException(404, "备份文件不存在")

    if not dry_run and confirmation != f"RESTORE-{backup_id}":
        raise HTTPException(400, f"请输入确认词 RESTORE-{backup_id}")
    backup_data = read_backup(Path(record.file_path))

    # 确定要恢复的表
    if tables:
        table_names = [t.strip() for t in tables.split(",")]
    else:
        table_names = list(backup_data.get("tables", {}).keys())

    restore_plan = {}
    for table_name in table_names:
        if table_name not in BACKUP_TABLES:
            raise HTTPException(400, f"未知表名: {table_name}")
        if table_name not in backup_data.get("tables", {}):
            continue

        rows = backup_data["tables"][table_name]
        model = BACKUP_TABLES[table_name]
        current_count = db.query(model).count()

        restore_plan[table_name] = {
            "backup_records": len(rows),
            "current_records": current_count,
            "action": "overwrite" if not dry_run else "preview_only",
        }

    if not dry_run:
        # 实际恢复：清空目标表并插入备份数据
        for table_name in table_names:
            if table_name not in backup_data.get("tables", {}):
                continue
            model = BACKUP_TABLES[table_name]
            rows = backup_data["tables"][table_name]

            # 删除现有数据
            db.query(model).delete()

            # 插入备份数据
            for row_data in rows:
                # 移除 id 让数据库自动生成（避免主键冲突）
                row_id = row_data.pop("id", None)
                # 转换日期字符串回 datetime
                for key in ["created_at", "updated_at", "parsed_at", "completed_at",
                            "since_checkpoint", "trade_date", "due_date"]:
                    if key in row_data and isinstance(row_data[key], str):
                        try:
                            if key in ("trade_date", "due_date"):
                                row_data[key] = date.fromisoformat(row_data[key])
                            else:
                                row_data[key] = datetime.fromisoformat(row_data[key])
                        except (ValueError, TypeError):
                            row_data[key] = None
                obj = model(**row_data)
                db.add(obj)

        db.commit()
        return {
            "status": "restored",
            "backup_id": backup_id,
            "tables": restore_plan,
            "message": f"已从备份 #{backup_id} 恢复 {len(table_names)} 个表",
        }
    else:
        return {
            "status": "dry_run",
            "backup_id": backup_id,
            "tables": restore_plan,
            "message": "预览模式，未实际恢复。设置 dry_run=false 执行恢复。",
        }


# ===== 财务目标管理 =====
