from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean, Date
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, date
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://silentbook:silentbook@localhost:5432/silentbook")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float, nullable=False)
    category = Column(String(50), nullable=False)
    account = Column(String(50), nullable=False)
    description = Column(Text)
    transaction_type = Column(String(20), nullable=False)  # income/expense
    raw_text = Column(Text)
    confidence = Column(Float, default=0.5)
    parsed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

class Asset(Base):
    """资产：现金、存款、基金、股票、理财、房产等"""
    __tablename__ = "assets"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    asset_type = Column(String(30), nullable=False)  # cash/savings/fund/stock/bond/property/other
    account = Column(String(100))  # 所属机构
    current_value = Column(Float, nullable=False, default=0)  # 当前价值
    initial_value = Column(Float, default=0)  # 初始投入
    currency = Column(String(10), default="CNY")
    liquidity = Column(String(10), default="medium")  # high/medium/low
    status = Column(String(20), default="active")  # active/frozen/closed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class Liability(Base):
    """负债：房贷/车贷/信用卡/花呗/白条等"""
    __tablename__ = "liabilities"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    liability_type = Column(String(30), nullable=False)  # mortgage/car_loan/credit_card/credit_card_installment/huabei/baitiao/loan/other
    total_amount = Column(Float, nullable=False, default=0)  # 总额
    current_amount = Column(Float, nullable=False, default=0)  # 当前待还
    interest_rate = Column(Float, default=0)  # 年利率
    monthly_payment = Column(Float, default=0)  # 月还款额
    remaining_periods = Column(Integer, default=0)  # 剩余期数（月）
    due_date = Column(Date)  # 到期日
    status = Column(String(20), default="active")  # active/paid/overdue
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
class AgentConfig(Base):
    __tablename__ = "agent_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    api_endpoint = Column(String(500), nullable=False)
    system_prompt = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Setting(Base):
    """系统设置：键值对存储"""
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), nullable=False, unique=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Account(Base):
    """四账户体系：消费/应急/投资/目标"""
    __tablename__ = "accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 账户名称（微信/招商银行卡等）
    account_type = Column(String(30), nullable=False)  # bank/alipay/wechat/cash/fund/stock/other
    purpose = Column(String(20), nullable=False)  # consumption/emergency/investment/goal
    balance = Column(Float, nullable=False, default=0)  # 当前余额
    target_balance = Column(Float, default=0)  # 目标余额
    currency = Column(String(10), default="CNY")
    status = Column(String(20), default="active")  # active/frozen/closed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(Base):
    """用户表：支持邮箱或手机号注册"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Transfer(Base):
    """账户间转账记录"""
    __tablename__ = "transfers"
    
    id = Column(Integer, primary_key=True, index=True)
    from_account_id = Column(Integer, nullable=False, index=True)
    to_account_id = Column(Integer, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String(100), nullable=False)
    analysis_type = Column(String(50), nullable=False)  # consumption/investment/suggestion
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
