from pydantic import BaseModel, Field, field_validator, ConfigDict, model_validator
from typing import Optional, List
from datetime import datetime
import re


class TransactionBase(BaseModel):
    amount: float = Field(..., ge=0, description="金额必须大于等于0")
    category: str = Field(..., min_length=1, max_length=50)
    account: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    transaction_type: str = Field(..., pattern="^(income|expense)$")
    raw_text: Optional[str] = Field(None, max_length=2000)
    confidence: float = Field(0.5, ge=0, le=1)

    @field_validator('transaction_type')
    @classmethod
    def validate_transaction_type(cls, v):
        if v not in ['income', 'expense']:
            raise ValueError('transaction_type must be income or expense')
        return v


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(BaseModel):
    """Partial update - all fields optional"""
    amount: Optional[float] = Field(None, ge=0)
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    account: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    transaction_type: Optional[str] = None
    raw_text: Optional[str] = Field(None, max_length=2000)
    confidence: Optional[float] = Field(None, ge=0, le=1)


class TransactionResponse(TransactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parsed_at: datetime


class AnalysisRequest(BaseModel):
    pass


class AnalysisResponse(BaseModel):
    consumption: str
    investment: str
    suggestion: str
    mode: str = "local"


class DashboardStats(BaseModel):
    net_assets: float
    total_assets: float = 0
    total_liabilities: float = 0
    monthly_income: float
    monthly_expenses: float
    transaction_count: int


# ===== 资产管理 =====

class AssetBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    asset_type: str = Field(..., pattern="^(cash|savings|fund|stock|bond|gold|pension|property|other)$")
    account: Optional[str] = Field(None, max_length=100)
    current_value: float = Field(0, ge=0)
    initial_value: float = Field(0, ge=0)
    currency: str = Field("CNY", max_length=10)
    liquidity: str = Field("medium", pattern="^(high|medium|low)$")
    status: str = Field("active", pattern="^(active|frozen|closed)$")
    notes: Optional[str] = Field(None, max_length=500)

class AssetCreate(AssetBase):
    pass

class AssetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    asset_type: Optional[str] = None
    account: Optional[str] = Field(None, max_length=100)
    current_value: Optional[float] = Field(None, ge=0)
    initial_value: Optional[float] = Field(None, ge=0)
    liquidity: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=500)

class AssetResponse(AssetBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


# ===== 负债管理 =====

class LiabilityBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    liability_type: str = Field(..., pattern="^(mortgage|car_loan|credit_card|credit_card_installment|huabei|baitiao|loan|other)$")
    total_amount: float = Field(0, ge=0)
    current_amount: float = Field(0, ge=0)
    interest_rate: float = Field(0, ge=0)
    monthly_payment: Optional[float] = Field(0, ge=0)  # 月还款额（允许NULL）
    remaining_periods: Optional[int] = Field(0, ge=0)  # 剩余期数（允许NULL）
    due_date: Optional[str] = None
    min_payment: Optional[float] = Field(0, ge=0)
    billing_day: Optional[int] = Field(1, ge=1, le=28)
    status: str = Field("active", pattern="^(active|paid|overdue)$")
    notes: Optional[str] = Field(None, max_length=500)

class LiabilityCreate(LiabilityBase):
    pass

class LiabilityUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    liability_type: Optional[str] = None
    total_amount: Optional[float] = Field(None, ge=0)
    current_amount: Optional[float] = Field(None, ge=0)
    interest_rate: Optional[float] = Field(None, ge=0)
    monthly_payment: Optional[float] = Field(None, ge=0)
    remaining_periods: Optional[int] = Field(None, ge=0)
    due_date: Optional[str] = None
    min_payment: Optional[float] = Field(0, ge=0)
    billing_day: Optional[int] = Field(1, ge=1, le=28)
    status: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=500)

class LiabilityResponse(LiabilityBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    monthly_payment: Optional[float] = Field(0, ge=0)
    remaining_periods: Optional[int] = Field(0, ge=0)
    created_at: datetime
    updated_at: datetime

    @field_validator('monthly_payment', 'remaining_periods', 'interest_rate', 'total_amount', 'current_amount', mode='before')
    @classmethod
    def none_to_zero(cls, v):
        return 0 if v is None else v


# ===== 用户认证 =====

class UserRegister(BaseModel):
    """注册：邮箱或手机号至少填一个"""
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    password: str = Field(..., min_length=6, max_length=128)
    nickname: Optional[str] = Field(None, max_length=50)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v is None:
            return None
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', v):
            raise ValueError('邮箱格式不正确')
        return v.lower().strip()

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v is None:
            return None
        if not re.match(r'^1[3-9]\d{9}$', v):
            raise ValueError('手机号格式不正确')
        return v.strip()

    @model_validator(mode='after')
    def at_least_one_contact(self):
        if not self.email and not self.phone:
            raise ValueError('邮箱和手机号至少填写一个')
        return self


class UserLogin(BaseModel):
    """登录：邮箱或手机号 + 密码"""
    account: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: Optional[str] = None
    phone: Optional[str] = None
    nickname: Optional[str] = None
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: 'UserResponse'


# ===== 密码找回 =====

class PasswordResetRequest(BaseModel):
    """请求密码重置：输入邮箱或手机号"""
    account: str = Field(..., min_length=1, max_length=255)


class PasswordResetConfirm(BaseModel):
    """重置密码：提交令牌 + 新密码"""
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


# ===== 多账户管理（四账户体系） =====

ACCOUNT_TYPES = {"bank", "alipay", "wechat", "cash", "fund", "stock", "other"}
ACCOUNT_PURPOSES = {"consumption", "emergency", "investment", "goal"}


class AccountBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    account_type: str = Field(..., pattern="^(bank|alipay|wechat|cash|fund|stock|other)$")
    purpose: str = Field(..., pattern="^(consumption|emergency|investment|goal)$")
    balance: float = Field(0)
    target_balance: float = Field(0)
    currency: str = Field("CNY", max_length=10)
    status: str = Field("active", pattern="^(active|frozen|closed)$")
    notes: Optional[str] = Field(None, max_length=500)


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    account_type: Optional[str] = None
    purpose: Optional[str] = None
    balance: Optional[float] = Field(None)
    target_balance: Optional[float] = Field(None)
    status: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=500)


class AccountResponse(AccountBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class AccountTransfer(BaseModel):
    """账户间转账"""
    from_account_id: int
    to_account_id: int
    amount: float = Field(..., gt=0)
    description: Optional[str] = Field(None, max_length=500)


class TransferResponse(BaseModel):
    """转账记录响应"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    from_account_id: int
    to_account_id: int
    amount: float
    description: Optional[str] = None
    created_at: datetime


# ===== 增量备份 =====

class BackupCreate(BaseModel):
    backup_type: str = Field("incremental", pattern="^(full|incremental)$")
    tables: Optional[List[str]] = None  # 指定备份的表，None=全部


class BackupTableDetail(BaseModel):
    table_name: str
    record_count: int
    new_records: int = 0
    updated_records: int = 0


class BackupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    backup_type: str
    status: str
    file_path: Optional[str] = None
    file_size: int = 0
    record_count: int = 0
    tables_backed_up: Optional[str] = None
    since_checkpoint: Optional[datetime] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0
    created_at: datetime
    completed_at: Optional[datetime] = None


class BackupStatusResponse(BaseModel):
    last_backup: Optional[datetime] = None
    last_backup_type: Optional[str] = None
    last_backup_status: Optional[str] = None
    total_backups: int = 0
    total_backup_size: int = 0
    next_scheduled_backup: Optional[str] = None
    backup_directory: str = ""
    auto_backup_enabled: bool = True


class RestoreRequest(BaseModel):
    backup_id: int
    tables: Optional[List[str]] = None  # 指定恢复的表，None=全部
    dry_run: bool = False  # True=只预览不实际恢复


# ===== 财务目标 =====

GOAL_TYPES = {"savings", "debt_payoff", "investment", "purchase"}
GOAL_PRIORITIES = {"high", "medium", "low"}
GOAL_STATUSES = {"active", "completed", "abandoned", "paused"}


class GoalBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    goal_type: str = Field(..., pattern="^(savings|debt_payoff|investment|purchase)$")
    target_amount: float = Field(..., gt=0, description="目标金额必须大于0")
    current_amount: float = Field(0, ge=0)
    currency: str = Field("CNY", max_length=10)
    deadline: Optional[str] = None  # ISO date string
    priority: str = Field("medium", pattern="^(high|medium|low)$")
    status: str = Field("active", pattern="^(active|completed|abandoned|paused)$")
    notes: Optional[str] = Field(None, max_length=500)


class GoalCreate(GoalBase):
    pass


class GoalUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    goal_type: Optional[str] = None
    target_amount: Optional[float] = Field(None, gt=0)
    current_amount: Optional[float] = Field(None, ge=0)
    deadline: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=500)


class GoalResponse(GoalBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    progress_percent: float = 0  # 进度百分比
    created_at: datetime
    updated_at: datetime


class GoalContributionCreate(BaseModel):
    amount: float = Field(..., gt=0, description="投入金额必须大于0")
    description: Optional[str] = Field(None, max_length=500)


class GoalContributionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    goal_id: int
    amount: float
    description: Optional[str] = None
    created_at: datetime


class GoalSummaryResponse(BaseModel):
    total_goals: int = 0
    active_goals: int = 0
    completed_goals: int = 0
    total_target: float = 0
    total_current: float = 0
    overall_progress: float = 0  # 0-100
    goals: List[GoalResponse] = []


# ===== 固定收支管理（V2-027） =====

RECURRING_FREQUENCIES = {"daily", "weekly", "biweekly", "monthly", "quarterly", "yearly"}
RECURRING_SOURCES = {"manual", "auto"}


class RecurringTransactionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., gt=0, description="金额必须大于0")
    category: str = Field(..., min_length=1, max_length=50)
    transaction_type: str = Field(..., pattern="^(income|expense)$")
    frequency: str = Field("monthly", pattern="^(daily|weekly|biweekly|monthly|quarterly|yearly)$")
    day_of_month: int = Field(1, ge=1, le=28, description="每月几号（1-28）")
    day_of_week: int = Field(0, ge=0, le=6, description="周几（0=周一，weekly用）")
    start_date: Optional[str] = None  # ISO date
    end_date: Optional[str] = None  # ISO date, None=永久
    account: Optional[str] = Field(None, max_length=100)
    is_active: bool = Field(True)
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator('transaction_type')
    @classmethod
    def validate_type(cls, v):
        if v not in ['income', 'expense']:
            raise ValueError('transaction_type must be income or expense')
        return v


class RecurringTransactionCreate(RecurringTransactionBase):
    pass


class RecurringTransactionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    amount: Optional[float] = Field(None, gt=0)
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    transaction_type: Optional[str] = None
    frequency: Optional[str] = None
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    account: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=500)


class RecurringTransactionResponse(RecurringTransactionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str = "manual"
    confidence: float = 1.0
    created_at: datetime
    updated_at: datetime


class RecurringSummaryResponse(BaseModel):
    """固定收支月度汇总"""
    total_monthly_income: float = 0
    total_monthly_expense: float = 0
    monthly_net: float = 0
    income_count: int = 0
    expense_count: int = 0
    active_count: int = 0
    items: List[RecurringTransactionResponse] = []


class AutoDetectResponse(BaseModel):
    """自动检测结果"""
    detected_count: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    items: List[dict] = []  # 检测到的候选项
