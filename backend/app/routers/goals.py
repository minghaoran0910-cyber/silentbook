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

def _calc_goal_progress(current_amount: float, target_amount: float) -> float:
    """计算目标进度百分比"""
    if target_amount <= 0:
        return 0.0
    return min(round((current_amount / target_amount) * 100, 2), 100.0)


def _goal_to_response(goal: FinancialGoal) -> GoalResponse:
    """将 ORM 对象转为响应模型"""
    return GoalResponse(
        id=goal.id,
        name=goal.name,
        goal_type=goal.goal_type,
        target_amount=goal.target_amount,
        current_amount=goal.current_amount,
        currency=goal.currency,
        deadline=goal.deadline.isoformat() if goal.deadline else None,
        priority=goal.priority,
        status=goal.status,
        notes=goal.notes,
        progress_percent=_calc_goal_progress(goal.current_amount, goal.target_amount),
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


@router.get("/goals/summary", response_model=GoalSummaryResponse)
async def get_goals_summary(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取所有目标的汇总概览"""
    goals = db.query(FinancialGoal).order_by(
        # 优先级排序：high > medium > low，然后按进度升序
        case((FinancialGoal.priority == "high", 1),
                  (FinancialGoal.priority == "medium", 2),
                  else_=3),
        FinancialGoal.created_at.desc()
    ).all()

    active = [g for g in goals if g.status == "active"]
    completed = [g for g in goals if g.status == "completed"]

    total_target = sum(g.target_amount for g in active)
    total_current = sum(g.current_amount for g in active)

    return GoalSummaryResponse(
        total_goals=len(goals),
        active_goals=len(active),
        completed_goals=len(completed),
        total_target=total_target,
        total_current=total_current,
        overall_progress=_calc_goal_progress(total_current, total_target),
        goals=[_goal_to_response(g) for g in goals],
    )


@router.get("/goals", response_model=List[GoalResponse])
async def list_goals(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    goal_type: Optional[str] = None,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """获取目标列表，支持筛选"""
    query = db.query(FinancialGoal)
    if status:
        query = query.filter(FinancialGoal.status == status)
    if priority:
        query = query.filter(FinancialGoal.priority == priority)
    if goal_type:
        query = query.filter(FinancialGoal.goal_type == goal_type)

    goals = query.order_by(
        case((FinancialGoal.priority == "high", 1),
                  (FinancialGoal.priority == "medium", 2),
                  else_=3),
        FinancialGoal.created_at.desc()
    ).all()

    return [_goal_to_response(g) for g in goals]


@router.post("/goals", response_model=GoalResponse, status_code=201)
async def create_goal(goal: GoalCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """创建新目标"""
    # 解析 deadline
    deadline_date = None
    if goal.deadline:
        try:
            deadline_date = date.fromisoformat(goal.deadline)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")

    db_goal = FinancialGoal(
        name=goal.name,
        goal_type=goal.goal_type,
        target_amount=goal.target_amount,
        current_amount=goal.current_amount,
        currency=goal.currency,
        deadline=deadline_date,
        priority=goal.priority,
        status=goal.status,
        notes=goal.notes,
    )
    db.add(db_goal)
    db.commit()
    db.refresh(db_goal)
    return _goal_to_response(db_goal)


@router.get("/goals/{goal_id}", response_model=GoalResponse)
async def get_goal(goal_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取单个目标详情"""
    goal = db.query(FinancialGoal).filter(FinancialGoal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    return _goal_to_response(goal)


@router.put("/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(goal_id: int, updates: GoalUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """更新目标"""
    goal = db.query(FinancialGoal).filter(FinancialGoal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")

    update_data = updates.model_dump(exclude_unset=True)

    # 处理 deadline
    if "deadline" in update_data:
        if update_data["deadline"]:
            try:
                update_data["deadline"] = date.fromisoformat(update_data["deadline"])
            except ValueError:
                raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")
        else:
            update_data["deadline"] = None

    # 如果状态改为 completed，自动设 current = target
    if update_data.get("status") == "completed":
        update_data["current_amount"] = goal.target_amount

    for key, value in update_data.items():
        setattr(goal, key, value)

    db.commit()
    db.refresh(goal)
    return _goal_to_response(goal)


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """删除目标（同时删除投入记录）"""
    goal = db.query(FinancialGoal).filter(FinancialGoal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")

    # 删除关联的投入记录
    db.query(GoalContribution).filter(GoalContribution.goal_id == goal_id).delete()
    db.delete(goal)
    db.commit()
    return {"message": f"目标 '{goal.name}' 已删除"}


@router.post("/goals/{goal_id}/contribute", response_model=GoalResponse)
async def contribute_to_goal(
    goal_id: int,
    contribution: GoalContributionCreate,
    user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """向目标投入资金"""
    goal = db.query(FinancialGoal).filter(FinancialGoal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    if goal.status != "active":
        raise HTTPException(status_code=400, detail="只能向进行中的目标投入资金")

    # 记录投入
    db_contribution = GoalContribution(
        goal_id=goal_id,
        amount=contribution.amount,
        description=contribution.description,
    )
    db.add(db_contribution)

    # 更新目标当前金额
    goal.current_amount += contribution.amount

    # 自动完成检查
    if goal.current_amount >= goal.target_amount:
        goal.status = "completed"

    db.commit()
    db.refresh(goal)
    return _goal_to_response(goal)


@router.get("/goals/{goal_id}/contributions", response_model=List[GoalContributionResponse])
async def list_contributions(goal_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """获取目标的投入记录"""
    goal = db.query(FinancialGoal).filter(FinancialGoal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")

    contributions = db.query(GoalContribution).filter(
        GoalContribution.goal_id == goal_id
    ).order_by(GoalContribution.created_at.desc()).all()

    return contributions


# ===== 固定收支管理（V2-027） =====
