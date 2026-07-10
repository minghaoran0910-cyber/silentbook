"""
SilentBook 定时任务调度器
- 通知清理：每6小时清理过期原始通知数据
- AI分析：每天20:00（北京时间）自动运行Agent分析
"""
import os
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from .database import SessionLocal, Transaction, AnalysisResult, BackupRecord

logger = logging.getLogger("silentbook.scheduler")


async def cleanup_old_notifications():
    """清理30天前的原始通知文本（节省存储空间）"""
    db: Session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)
        count = db.query(Transaction).filter(
            Transaction.parsed_at < cutoff,
            Transaction.raw_text.isnot(None)
        ).update({"raw_text": None}, synchronize_session=False)
        db.commit()
        if count > 0:
            logger.info(f"已清理 {count} 条过期原始通知文本")
    except Exception as e:
        logger.error(f"清理通知失败: {e}")
        db.rollback()
    finally:
        db.close()


async def scheduled_daily_analysis():
    """每天20:00自动运行AI分析"""
    db: Session = SessionLocal()
    try:
        # 获取最近交易数据
        transactions = db.query(Transaction).order_by(
            Transaction.parsed_at.desc()
        ).limit(100).all()

        if len(transactions) < 3:
            logger.info("交易数据不足（<3条），跳过自动分析")
            return

        # 检查今天是否已经分析过
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_analyses = db.query(AnalysisResult).filter(
            AnalysisResult.created_at >= today_start
        ).count()

        if today_analyses > 0:
            logger.info("今天已有分析记录，跳过自动分析")
            return

        # 调用 Agent API
        import httpx
        import os
        agent_url = os.getenv("AGENT_API_URL", "http://agent:5000")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{agent_url}/analyze",
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
                    "assets": [],
                    "liabilities": []
                },
                timeout=90.0
            )
            result = response.json()

        # 保存分析结果
        agent_name = result.get("mode", "scheduled")
        for analysis_type in ["consumption", "investment", "suggestion"]:
            analysis = AnalysisResult(
                agent_name=f"scheduled-{agent_name}",
                analysis_type=analysis_type,
                content=result.get(analysis_type, "暂无分析")
            )
            db.add(analysis)
        db.commit()
        logger.info("定时分析完成，已保存结果")

    except Exception as e:
        logger.error(f"定时分析失败: {e}")
        db.rollback()
    finally:
        db.close()


async def _run_backup(backup_type: str = "incremental"):
    """执行备份的通用逻辑"""
    import json
    import gzip
    import time as _time
    from pathlib import Path
    from datetime import datetime, date
    from .database import (
        Transaction, Asset, Liability, Account, Position,
        TradeRecord, Transfer, AgentConfig, Setting, User
    )

    BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/tmp/silentbook-backups"))
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

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

    start_time = _time.time()
    db: Session = SessionLocal()

    try:
        # 获取上次备份时间点
        since = None
        if backup_type == "incremental":
            last = db.query(BackupRecord).filter(
                BackupRecord.status == "completed",
                BackupRecord.backup_type == "incremental"
            ).order_by(BackupRecord.created_at.desc()).first()
            if last and last.completed_at:
                since = last.completed_at

        # 创建备份记录
        record = BackupRecord(
            backup_type=backup_type,
            status="running",
            since_checkpoint=since,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        backup_data = {"metadata": {}, "tables": {}}
        table_details = {}
        total_records = 0

        for table_name, model in BACKUP_TABLES.items():
            rows = db.query(model).all()
            serialized = []
            for row in rows:
                data = {}
                for col in model.__table__.columns:
                    val = getattr(row, col.name, None)
                    if isinstance(val, (datetime, date)):
                        val = val.isoformat()
                    data[col.name] = val
                serialized.append(data)

            backup_data["tables"][table_name] = serialized
            table_details[table_name] = {"record_count": len(serialized)}
            total_records += len(serialized)

        backup_data["metadata"] = {
            "backup_id": record.id,
            "backup_type": backup_type,
            "created_at": datetime.utcnow().isoformat(),
            "since_checkpoint": since.isoformat() if since else None,
            "total_records": total_records,
        }

        # 写入压缩文件
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{record.id}_{timestamp}.json.gz"
        file_path = BACKUP_DIR / filename

        with gzip.open(file_path, "wt", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, default=str)

        file_size = file_path.stat().st_size
        duration = _time.time() - start_time

        record.status = "completed"
        record.file_path = str(file_path)
        record.file_size = file_size
        record.record_count = total_records
        record.tables_backed_up = json.dumps(table_details, ensure_ascii=False)
        record.duration_seconds = round(duration, 2)
        record.completed_at = datetime.utcnow()
        db.commit()

        logger.info(f"定时{backup_type}备份完成: {total_records}条记录, {file_size}字节, 耗时{duration:.1f}s")

    except Exception as e:
        logger.error(f"定时备份失败: {e}")
        try:
            record.status = "failed"
            record.error_message = str(e)
            record.completed_at = datetime.utcnow()
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def scheduled_incremental_backup():
    """每日03:00增量备份"""
    await _run_backup("incremental")


async def scheduled_full_backup():
    """每周日04:00全量备份"""
    await _run_backup("full")


def create_scheduler() -> AsyncIOScheduler:
    """创建并配置调度器"""
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    # 通知清理：每6小时执行一次
    scheduler.add_job(
        cleanup_old_notifications,
        trigger=IntervalTrigger(hours=6),
        id="cleanup_notifications",
        name="清理过期通知数据",
        replace_existing=True
    )

    # AI分析：每天20:00（北京时间）
    scheduler.add_job(
        scheduled_daily_analysis,
        trigger=CronTrigger(hour=20, minute=0, timezone="Asia/Shanghai"),
        id="daily_analysis",
        name="每日20:00自动分析",
        replace_existing=True
    )

    # 增量备份：每天03:00（北京时间）
    scheduler.add_job(
        scheduled_incremental_backup,
        trigger=CronTrigger(hour=3, minute=0, timezone="Asia/Shanghai"),
        id="incremental_backup",
        name="每日03:00增量备份",
        replace_existing=True
    )

    # 全量备份：每周日04:00（北京时间）
    scheduler.add_job(
        scheduled_full_backup,
        trigger=CronTrigger(day_of_week="sun", hour=4, minute=0, timezone="Asia/Shanghai"),
        id="full_backup",
        name="每周日04:00全量备份",
        replace_existing=True
    )

    return scheduler
