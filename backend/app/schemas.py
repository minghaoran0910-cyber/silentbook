from pydantic import BaseModel, Field, field_validator, ConfigDict, model_validator
from typing import Optional
from datetime import datetime
import re


class TransactionBase(BaseModel):
    amount: float = Field(..., gt=0, description="金额必须大于0")
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
    amount: Optional[float] = Field(None, gt=0)
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
    asset_type: str = Field(..., pattern="^(cash|savings|fund|stock|bond|property|other)$")
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
    liability_type: str = Field(..., pattern="^(credit_card|loan|mortgage|other)$")
    total_amount: float = Field(0, ge=0)
    current_amount: float = Field(0, ge=0)
    interest_rate: float = Field(0, ge=0)
    due_date: Optional[str] = None
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
    due_date: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=500)

class LiabilityResponse(LiabilityBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


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
