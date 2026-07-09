"""
SilentBook 定时任务调度器
- 通知清理：每6小时清理过期原始通知数据
- AI分析：每天20:00（北京时间）自动运行Agent分析
"""
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from .database import SessionLocal, Transaction, AnalysisResult

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

    return scheduler
