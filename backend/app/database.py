from sqlalchemy import create_engine, Column, Integer, String, Float, Numeric, DateTime, Text, Boolean, Date, Index, ForeignKey, event
from sqlalchemy.orm import declarative_base, sessionmaker, with_loader_criteria, Session
from datetime import datetime, date
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://silentbook:silentbook@localhost:5432/silentbook")

_engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    # FastAPI 在线程池中执行同步端点，SQLite 连接必须允许跨线程使用
    _engine_options["connect_args"] = {"check_same_thread": False}
else:
    _engine_options.update(
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=1800,
    )
engine = create_engine(DATABASE_URL, **_engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
# PostgreSQL stores exact decimals; existing API calculations continue to receive
# floats until the response schema is migrated independently.
Money = Numeric(18, 2, asdecimal=False)
Quantity = Numeric(24, 8, asdecimal=False)


class UserOwnedMixin:
    """Marks business data that must always belong to exactly one user."""

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

class Transaction(UserOwnedMixin, Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Money, nullable=False)
    category = Column(String(50), nullable=False, index=True)
    account = Column(String(50), nullable=False, index=True)
    description = Column(Text)
    transaction_type = Column(String(20), nullable=False, index=True)  # income/expense
    raw_text = Column(Text)
    confidence = Column(Float, default=0.5)
    parsed_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # 复合索引：按时间范围+类型查询（月报、现金流报表高频使用）
        Index('ix_transactions_type_parsed', 'transaction_type', 'parsed_at'),
        # 复合索引：按分类+时间查询（支出结构报表）
        Index('ix_transactions_category_parsed', 'category', 'parsed_at'),
        # 复合索引：按账户+时间查询
        Index('ix_transactions_account_parsed', 'account', 'parsed_at'),
    )

class Asset(UserOwnedMixin, Base):
    """资产：现金、存款、基金、股票、理财、房产等"""
    __tablename__ = "assets"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    asset_type = Column(String(30), nullable=False, index=True)  # cash/savings/fund/stock/bond/gold/pension/property/other
    account = Column(String(100))  # 所属机构
    current_value = Column(Money, nullable=False, default=0)  # 当前价值
    initial_value = Column(Money, default=0)  # 初始投入
    currency = Column(String(10), default="CNY")
    liquidity = Column(String(10), default="medium")  # high/medium/low
    status = Column(String(20), default="active", index=True)  # active/frozen/closed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class Liability(UserOwnedMixin, Base):
    """负债：房贷/车贷/信用卡/花呗/白条等"""
    __tablename__ = "liabilities"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    liability_type = Column(String(30), nullable=False, index=True)  # mortgage/car_loan/credit_card/credit_card_installment/huabei/baitiao/loan/other
    total_amount = Column(Money, nullable=False, default=0)  # 总额
    current_amount = Column(Money, nullable=False, default=0)  # 当前待还
    interest_rate = Column(Float, default=0)  # 年利率
    monthly_payment = Column(Money, default=0)  # 月还款额
    remaining_periods = Column(Integer, default=0)  # 剩余期数（月）
    due_date = Column(Date)  # 到期日
    min_payment = Column(Money, default=0)  # 最低还款/本期应还
    billing_day = Column(Integer, default=1)  # 账单日（每月几号）
    status = Column(String(20), default="active", index=True)  # active/paid/overdue
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class AgentConfig(UserOwnedMixin, Base):
    __tablename__ = "agent_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    api_endpoint = Column(String(500), nullable=False)
    system_prompt = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Setting(UserOwnedMixin, Base):
    """系统设置:键值对存储"""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("uq_settings_user_key", "user_id", "key", unique=True),)


class Account(UserOwnedMixin, Base):
    """四账户体系：消费/应急/投资/目标"""
    __tablename__ = "accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 账户名称（微信/招商银行卡等）
    account_type = Column(String(30), nullable=False)  # bank/alipay/wechat/cash/fund/stock/other
    purpose = Column(String(20), nullable=False, index=True)  # consumption/emergency/investment/goal
    balance = Column(Money, nullable=False, default=0)  # 当前余额
    target_balance = Column(Money, default=0)  # 目标余额
    currency = Column(String(10), default="CNY")
    status = Column(String(20), default="active", index=True)  # active/frozen/closed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(Base):
    """用户表:支持邮箱或手机号注册"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Transfer(UserOwnedMixin, Base):
    """账户间转账记录"""
    __tablename__ = "transfers"
    
    id = Column(Integer, primary_key=True, index=True)
    from_account_id = Column(Integer, nullable=False, index=True)
    to_account_id = Column(Integer, nullable=False, index=True)
    amount = Column(Money, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AnalysisResult(UserOwnedMixin, Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String(100), nullable=False)
    analysis_type = Column(String(50), nullable=False, index=True)  # consumption/investment/suggestion
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Position(UserOwnedMixin, Base):
    """投资持仓：股票/基金/理财产品"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 持仓名称（如"沪深300ETF"）
    symbol = Column(String(20))  # 代码（如 510300）
    position_type = Column(String(20), nullable=False, index=True)  # stock/fund/bond/wealth_mgmt/other
    quantity = Column(Quantity, default=0)  # 持有份额/股数
    avg_cost = Column(Quantity, default=0)  # 平均成本价
    current_price = Column(Quantity, default=0)  # 当前价格/净值
    currency = Column(String(10), default="CNY")
    account = Column(String(100))  # 所属账户（证券账户等）
    status = Column(String(20), default="active", index=True)  # active/closed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TradeRecord(UserOwnedMixin, Base):
    """投资交易记录：买入/卖出/分红"""
    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(Integer, nullable=False, index=True)  # 关联持仓
    trade_type = Column(String(20), nullable=False, index=True)  # buy/sell/dividend
    quantity = Column(Quantity, nullable=False)  # 数量
    price = Column(Quantity, nullable=False)  # 成交价
    amount = Column(Money, nullable=False)  # 成交金额
    fee = Column(Money, default=0)  # 手续费
    trade_date = Column(Date, nullable=False, index=True)  # 交易日期
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


class FinancialGoal(UserOwnedMixin, Base):
    """财务目标：买房首付/应急基金/旅行基金等"""
    __tablename__ = "financial_goals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 目标名称
    goal_type = Column(String(30), nullable=False, index=True)  # savings/debt_payoff/investment/purchase
    target_amount = Column(Money, nullable=False, default=0)  # 目标金额
    current_amount = Column(Money, nullable=False, default=0)  # 当前已积累
    currency = Column(String(10), default="CNY")
    deadline = Column(Date)  # 目标达成日期
    priority = Column(String(10), default="medium")  # high/medium/low
    status = Column(String(20), default="active", index=True)  # active/completed/abandoned/paused
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GoalContribution(UserOwnedMixin, Base):
    """目标投入记录:每次往目标里存钱"""
    __tablename__ = "goal_contributions"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, nullable=False, index=True)  # 关联目标
    amount = Column(Money, nullable=False)  # 投入金额
    description = Column(Text)  # 备注
    created_at = Column(DateTime, default=datetime.utcnow)


class RecurringTransaction(UserOwnedMixin, Base):
    """固定收支：工资/房租/订阅/保险等周期性收支"""
    __tablename__ = "recurring_transactions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # 名称（如"工资""房租""Netflix"）
    amount = Column(Money, nullable=False)  # 金额
    category = Column(String(50), nullable=False, index=True)  # 分类
    transaction_type = Column(String(20), nullable=False, index=True)  # income/expense
    frequency = Column(String(20), nullable=False, default="monthly")  # daily/weekly/biweekly/monthly/quarterly/yearly
    day_of_month = Column(Integer, default=1)  # 每月几号（1-28）
    day_of_week = Column(Integer, default=0)  # 周几（0=周一，weekly用）
    start_date = Column(Date, nullable=True)  # 生效日期
    end_date = Column(Date, nullable=True)  # 结束日期（None=永久）
    account = Column(String(100))  # 关联账户
    is_active = Column(Boolean, default=True, index=True)  # 是否启用
    source = Column(String(20), default="manual")  # manual(手动)/auto(自动检测)
    confidence = Column(Float, default=1.0)  # 自动检测时的置信度
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncLog(UserOwnedMixin, Base):
    """资产同步日志"""
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    sync_type = Column(String(20), nullable=False, default="auto")  # auto(定时)/manual(手动)
    status = Column(String(20), nullable=False, default="running")  # running/completed/failed
    total_count = Column(Integer, default=0)  # 总持仓数
    updated_count = Column(Integer, default=0)  # 成功更新数
    failed_count = Column(Integer, default=0)  # 失败数
    skipped_count = Column(Integer, default=0)  # 跳过数
    details = Column(Text)  # JSON: 同步详情
    error_message = Column(Text)  # 失败原因
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


class BackupRecord(UserOwnedMixin, Base):
    """增量备份记录"""
    __tablename__ = "backup_records"

    id = Column(Integer, primary_key=True, index=True)
    backup_type = Column(String(20), nullable=False, default="incremental")  # full/incremental
    status = Column(String(20), nullable=False, default="running", index=True)  # running/completed/failed
    file_path = Column(String(500))  # 备份文件路径
    file_size = Column(Integer, default=0)  # 文件大小(bytes)
    record_count = Column(Integer, default=0)  # 备份记录总数
    tables_backed_up = Column(Text)  # JSON: 各表备份的记录数
    since_checkpoint = Column(DateTime)  # 上次备份的时间点（增量备份用）
    error_message = Column(Text)  # 失败原因
    duration_seconds = Column(Float, default=0)  # 备份耗时
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime)


class WebhookEvent(UserOwnedMixin, Base):
    """Persisted idempotency/replay guard for signed webhook requests."""

    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(128), nullable=False)
    signature_timestamp = Column(Integer, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("uq_webhook_events_user_event", "user_id", "event_id", unique=True),
    )


@event.listens_for(Session, "do_orm_execute")
def _enforce_tenant_reads(execute_state):
    """Apply tenant criteria to ORM reads, updates and deletes."""
    if (
        not (execute_state.is_select or execute_state.is_update or execute_state.is_delete)
        or execute_state.execution_options.get("skip_tenant_scope")
    ):
        return
    from .tenant import get_tenant_user_id

    user_id = get_tenant_user_id()
    scoped_user_id = user_id if user_id is not None else -1
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            UserOwnedMixin,
            lambda model: model.user_id == scoped_user_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _enforce_tenant_writes(session, flush_context, instances):
    """Assign ownership on inserts and reject cross-tenant writes."""
    from .tenant import get_tenant_user_id

    user_id = get_tenant_user_id()
    if user_id is None:
        return
    for obj in session.new:
        if isinstance(obj, UserOwnedMixin):
            if obj.user_id is None:
                obj.user_id = user_id
            elif obj.user_id != user_id:
                raise ValueError("cross-tenant insert rejected")
    for obj in session.dirty | session.deleted:
        if isinstance(obj, UserOwnedMixin) and obj.user_id != user_id:
            raise ValueError("cross-tenant write rejected")
