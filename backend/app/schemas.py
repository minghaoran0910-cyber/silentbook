from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional
from datetime import datetime


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


class DashboardStats(BaseModel):
    net_assets: float
    monthly_income: float
    monthly_expenses: float
    transaction_count: int
