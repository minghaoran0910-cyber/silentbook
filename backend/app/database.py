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


class Position(Base):
    """投资持仓：股票/基金/理财产品"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 持仓名称（如“沪深300ETF”）
    symbol = Column(String(20))  # 代码（如 510300）
    position_type = Column(String(20), nullable=False)  # stock/fund/bond/wealth_mgmt/other
    quantity = Column(Float, default=0)  # 持有份额/股数
    avg_cost = Column(Float, default=0)  # 平均成本价
    current_price = Column(Float, default=0)  # 当前价格/净值
    currency = Column(String(10), default="CNY")
    account = Column(String(100))  # 所属账户（证券账户等）
    status = Column(String(20), default="active")  # active/closed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TradeRecord(Base):
    """投资交易记录：买入/卖出/分红"""
    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(Integer, nullable=False, index=True)  # 关联持仓
    trade_type = Column(String(20), nullable=False)  # buy/sell/dividend
    quantity = Column(Float, nullable=False)  # 数量
    price = Column(Float, nullable=False)  # 成交价
    amount = Column(Float, nullable=False)  # 成交金额
    fee = Column(Float, default=0)  # 手续费
    trade_date = Column(Date, nullable=False)  # 交易日期
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class FinancialGoal(Base):
    """财务目标：买房首付/应急基金/旅行基金等"""
    __tablename__ = "financial_goals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 目标名称
    goal_type = Column(String(30), nullable=False)  # savings/debt_payoff/investment/purchase
    target_amount = Column(Float, nullable=False, default=0)  # 目标金额
    current_amount = Column(Float, nullable=False, default=0)  # 当前已积累
    currency = Column(String(10), default="CNY")
    deadline = Column(Date)  # 目标达成日期
    priority = Column(String(10), default="medium")  # high/medium/low
    status = Column(String(20), default="active")  # active/completed/abandoned/paused
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GoalContribution(Base):
    """目标投入记录：每次往目标里存钱"""
    __tablename__ = "goal_contributions"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, nullable=False, index=True)  # 关联目标
    amount = Column(Float, nullable=False)  # 投入金额
    description = Column(Text)  # 备注
    created_at = Column(DateTime, default=datetime.utcnow)


class RecurringTransaction(Base):
    """固定收支：工资/房租/订阅/保险等周期性收支"""
    __tablename__ = "recurring_transactions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 名称（如"工资""房租""Netflix"）
    amount = Column(Float, nullable=False)  # 金额
    category = Column(String(50), nullable=False)  # 分类
    transaction_type = Column(String(20), nullable=False)  # income/expense
    frequency = Column(String(20), nullable=False, default="monthly")  # daily/weekly/biweekly/monthly/quarterly/yearly
    day_of_month = Column(Integer, default=1)  # 每月几号（1-28）
    day_of_week = Column(Integer, default=0)  # 周几（0=周一，weekly用）
    start_date = Column(Date, nullable=True)  # 生效日期
    end_date = Column(Date, nullable=True)  # 结束日期（None=永久）
    account = Column(String(100))  # 关联账户
    is_active = Column(Boolean, default=True)  # 是否启用
    source = Column(String(20), default="manual")  # manual(手动)/auto(自动检测)
    confidence = Column(Float, default=1.0)  # 自动检测时的置信度
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BackupRecord(Base):
    """增量备份记录"""
    __tablename__ = "backup_records"

    id = Column(Integer, primary_key=True, index=True)
    backup_type = Column(String(20), nullable=False, default="incremental")  # full/incremental
    status = Column(String(20), nullable=False, default="running")  # running/completed/failed
    file_path = Column(String(500))  # 备份文件路径
    file_size = Column(Integer, default=0)  # 文件大小(bytes)
    record_count = Column(Integer, default=0)  # 备份记录总数
    tables_backed_up = Column(Text)  # JSON: 各表备份的记录数
    since_checkpoint = Column(DateTime)  # 上次备份的时间点（增量备份用）
    error_message = Column(Text)  # 失败原因
    duration_seconds = Column(Float, default=0)  # 备份耗时
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
