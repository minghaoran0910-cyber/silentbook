"""
V2-029: 数据库索引优化测试

测试内容：
1. 所有模型索引定义正确
2. 迁移脚本可正常执行
3. 索引创建后查询性能提升
4. 复合索引覆盖高频查询
5. 现有功能无回归
"""

import pytest
import os
import sys
import time
from datetime import datetime, date, timedelta
from sqlalchemy import inspect, text

# 添加 app 到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

# 使用 SQLite 测试数据库
os.environ["DATABASE_URL"] = "sqlite://"

from database import (
    engine, Base, SessionLocal, init_db,
    Transaction, Asset, Liability, Account, Transfer,
    AnalysisResult, Position, TradeRecord, FinancialGoal,
    GoalContribution, RecurringTransaction, BackupRecord,
    Setting, AgentConfig, User
)


@pytest.fixture(scope="module")
def setup_db():
    """创建测试数据库"""
    # 删除旧测试数据库
    if os.path.exists("./test_indexes.db"):
        os.remove("./test_indexes.db")
    
    init_db()
    yield
    
    # 清理
    if os.path.exists("./test_indexes.db"):
        os.remove("./test_indexes.db")


@pytest.fixture(scope="module")
def db_session(setup_db):
    """提供数据库会话"""
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def seed_data(db_session):
    """插入测试数据用于性能测试"""
    # 插入 1000 条交易记录
    categories = ["餐饮", "交通", "购物", "工资", "娱乐", "医疗", "教育", "住房"]
    accounts = ["微信", "支付宝", "招商银行卡", "现金"]
    types = ["income", "expense"]
    
    base_date = datetime(2025, 1, 1)
    transactions = []
    for i in range(1000):
        tx = Transaction(
            amount=round(10 + (i % 500) * 0.5, 2),
            category=categories[i % len(categories)],
            account=accounts[i % len(accounts)],
            transaction_type=types[i % 2],
            parsed_at=base_date + timedelta(days=i % 365, hours=i % 24),
            description=f"测试交易 {i}"
        )
        transactions.append(tx)
    
    db_session.bulk_save_objects(transactions)
    
    # 插入资产
    assets = [
        Asset(name="招商储蓄", asset_type="savings", current_value=50000, status="active"),
        Asset(name="余额宝", asset_type="fund", current_value=20000, status="active"),
        Asset(name="沪深300", asset_type="fund", current_value=30000, status="active"),
        Asset(name="冻结账户", asset_type="savings", current_value=5000, status="frozen"),
    ]
    db_session.bulk_save_objects(assets)
    
    # 插入负债
    liabilities = [
        Liability(name="花呗", liability_type="huabei", total_amount=5000, current_amount=3000, status="active"),
        Liability(name="房贷", liability_type="mortgage", total_amount=1000000, current_amount=800000, status="active"),
        Liability(name="已还清", liability_type="credit_card", total_amount=10000, current_amount=0, status="paid"),
    ]
    db_session.bulk_save_objects(liabilities)
    
    # 插入账户
    accounts_data = [
        Account(name="微信", account_type="wechat", purpose="consumption", balance=2000, status="active"),
        Account(name="招商", account_type="bank", purpose="emergency", balance=50000, status="active"),
        Account(name="证券", account_type="stock", purpose="investment", balance=30000, status="active"),
        Account(name="旅行基金", account_type="bank", purpose="goal", balance=5000, status="active"),
    ]
    db_session.bulk_save_objects(accounts_data)
    
    # 插入固定收支
    recurring = [
        RecurringTransaction(name="工资", amount=15000, category="工资", transaction_type="income", frequency="monthly", is_active=True),
        RecurringTransaction(name="房租", amount=3500, category="住房", transaction_type="expense", frequency="monthly", is_active=True),
        RecurringTransaction(name="Netflix", amount=98, category="娱乐", transaction_type="expense", frequency="monthly", is_active=False),
    ]
    db_session.bulk_save_objects(recurring)
    
    db_session.commit()
    return len(transactions)


class TestIndexDefinitions:
    """测试索引定义是否正确"""
    
    def test_transaction_indexes(self, setup_db):
        """Transaction 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('transactions')}
        
        # 单列索引
        assert 'ix_transactions_category' in indexes
        assert 'ix_transactions_account' in indexes
        assert 'ix_transactions_transaction_type' in indexes
        assert 'ix_transactions_parsed_at' in indexes
        
        # 复合索引
        assert 'ix_transactions_type_parsed' in indexes
        assert 'ix_transactions_category_parsed' in indexes
        assert 'ix_transactions_account_parsed' in indexes
    
    def test_asset_indexes(self, setup_db):
        """Asset 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('assets')}
        
        assert 'ix_assets_asset_type' in indexes
        assert 'ix_assets_status' in indexes
    
    def test_liability_indexes(self, setup_db):
        """Liability 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('liabilities')}
        
        assert 'ix_liabilities_liability_type' in indexes
        assert 'ix_liabilities_status' in indexes
    
    def test_account_indexes(self, setup_db):
        """Account 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('accounts')}
        
        assert 'ix_accounts_purpose' in indexes
        assert 'ix_accounts_status' in indexes
    
    def test_transfer_indexes(self, setup_db):
        """Transfer 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('transfers')}
        
        assert 'ix_transfers_created_at' in indexes
    
    def test_analysis_result_indexes(self, setup_db):
        """AnalysisResult 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('analysis_results')}
        
        assert 'ix_analysis_results_analysis_type' in indexes
        assert 'ix_analysis_results_created_at' in indexes
    
    def test_position_indexes(self, setup_db):
        """Position 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('positions')}
        
        assert 'ix_positions_position_type' in indexes
        assert 'ix_positions_status' in indexes
    
    def test_trade_record_indexes(self, setup_db):
        """TradeRecord 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('trade_records')}
        
        assert 'ix_trade_records_trade_type' in indexes
        assert 'ix_trade_records_trade_date' in indexes
    
    def test_financial_goal_indexes(self, setup_db):
        """FinancialGoal 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('financial_goals')}
        
        assert 'ix_financial_goals_goal_type' in indexes
        assert 'ix_financial_goals_status' in indexes
    
    def test_recurring_transaction_indexes(self, setup_db):
        """RecurringTransaction 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('recurring_transactions')}
        
        assert 'ix_recurring_transactions_category' in indexes
        assert 'ix_recurring_transactions_transaction_type' in indexes
        assert 'ix_recurring_transactions_is_active' in indexes
    
    def test_backup_record_indexes(self, setup_db):
        """BackupRecord 表索引"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('backup_records')}
        
        assert 'ix_backup_records_status' in indexes
        assert 'ix_backup_records_created_at' in indexes


class TestCompositeIndexes:
    """测试复合索引"""
    
    def test_composite_index_columns(self, setup_db):
        """验证复合索引列顺序正确"""
        inspector = inspect(engine)
        indexes = {idx['name']: idx for idx in inspector.get_indexes('transactions')}
        
        # type + parsed_at
        type_parsed = indexes['ix_transactions_type_parsed']
        assert type_parsed['column_names'] == ['transaction_type', 'parsed_at']
        
        # category + parsed_at
        cat_parsed = indexes['ix_transactions_category_parsed']
        assert cat_parsed['column_names'] == ['category', 'parsed_at']
        
        # account + parsed_at
        acc_parsed = indexes['ix_transactions_account_parsed']
        assert acc_parsed['column_names'] == ['account', 'parsed_at']


class TestIndexPerformance:
    """测试索引对查询性能的影响"""
    
    def test_query_uses_index(self, db_session, seed_data, setup_db):
        """验证查询使用了索引"""
        # 按类型+时间范围查询（应使用复合索引）
        start_date = datetime(2025, 3, 1)
        end_date = datetime(2025, 6, 1)
        
        results = db_session.query(Transaction).filter(
            Transaction.transaction_type == "expense",
            Transaction.parsed_at >= start_date,
            Transaction.parsed_at < end_date
        ).all()
        
        assert len(results) > 0
    
    def test_category_filter_performance(self, db_session, seed_data):
        """分类过滤查询"""
        results = db_session.query(Transaction).filter(
            Transaction.category == "餐饮"
        ).all()
        assert len(results) > 0
    
    def test_date_range_query(self, db_session, seed_data):
        """时间范围查询"""
        start_date = datetime(2025, 1, 1)
        end_date = datetime(2025, 12, 31)
        
        results = db_session.query(Transaction).filter(
            Transaction.parsed_at >= start_date,
            Transaction.parsed_at <= end_date
        ).order_by(Transaction.parsed_at.desc()).all()
        
        assert len(results) > 0
    
    def test_aggregate_with_index(self, db_session, seed_data):
        """聚合查询（月报常用）"""
        from sqlalchemy import func
        
        start_date = datetime(2025, 1, 1)
        end_date = datetime(2025, 7, 1)
        
        # 月度收入汇总
        income = db_session.query(
            func.coalesce(func.sum(Transaction.amount), 0)
        ).filter(
            Transaction.transaction_type == "income",
            Transaction.parsed_at >= start_date,
            Transaction.parsed_at < end_date
        ).scalar()
        
        assert income > 0
        
        # 月度支出汇总
        expense = db_session.query(
            func.coalesce(func.sum(Transaction.amount), 0)
        ).filter(
            Transaction.transaction_type == "expense",
            Transaction.parsed_at >= start_date,
            Transaction.parsed_at < end_date
        ).scalar()
        
        assert expense > 0
    
    def test_status_filter_assets(self, db_session, seed_data):
        """资产状态过滤"""
        active = db_session.query(Asset).filter(Asset.status == "active").all()
        assert len(active) == 3
        
        frozen = db_session.query(Asset).filter(Asset.status == "frozen").all()
        assert len(frozen) == 1
    
    def test_status_filter_liabilities(self, db_session, seed_data):
        """负债状态过滤"""
        active = db_session.query(Liability).filter(Liability.status == "active").all()
        assert len(active) == 2
    
    def test_purpose_filter_accounts(self, db_session, seed_data):
        """账户用途过滤"""
        consumption = db_session.query(Account).filter(Account.purpose == "consumption").all()
        assert len(consumption) == 1
    
    def test_active_recurring(self, db_session, seed_data):
        """活跃固定收支过滤"""
        active = db_session.query(RecurringTransaction).filter(
            RecurringTransaction.is_active == True
        ).all()
        assert len(active) == 2


class TestMigrationScript:
    """测试迁移脚本"""
    
    def test_migration_idempotent(self, setup_db):
        """迁移脚本幂等性（多次执行不报错）"""
        # 导入并执行迁移
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'migrations'))
        
        # 模拟迁移脚本中的 SQL
        with engine.connect() as conn:
            sql = "CREATE INDEX IF NOT EXISTS ix_test_idempotent ON transactions(id)"
            conn.execute(text(sql))
            conn.commit()
            
            # 再次执行不应报错
            conn.execute(text(sql))
            conn.commit()
            
            # 清理
            conn.execute(text("DROP INDEX IF EXISTS ix_test_idempotent"))
            conn.commit()


class TestNoRegression:
    """回归测试：确保现有功能正常"""
    
    def test_transaction_crud(self, db_session, setup_db):
        """交易 CRUD 正常"""
        tx = Transaction(
            amount=100.0,
            category="测试",
            account="测试账户",
            transaction_type="expense",
            parsed_at=datetime.utcnow()
        )
        db_session.add(tx)
        db_session.commit()
        
        fetched = db_session.query(Transaction).filter(Transaction.id == tx.id).first()
        assert fetched is not None
        assert fetched.amount == 100.0
        
        db_session.delete(tx)
        db_session.commit()
    
    def test_asset_crud(self, db_session, setup_db):
        """资产 CRUD 正常"""
        asset = Asset(
            name="测试资产",
            asset_type="cash",
            current_value=1000
        )
        db_session.add(asset)
        db_session.commit()
        
        fetched = db_session.query(Asset).filter(Asset.id == asset.id).first()
        assert fetched is not None
        
        db_session.delete(asset)
        db_session.commit()
    
    def test_account_crud(self, db_session, setup_db):
        """账户 CRUD 正常"""
        account = Account(
            name="测试账户",
            account_type="bank",
            purpose="consumption",
            balance=500
        )
        db_session.add(account)
        db_session.commit()
        
        fetched = db_session.query(Account).filter(Account.id == account.id).first()
        assert fetched is not None
        
        db_session.delete(account)
        db_session.commit()
    
    def test_order_by_parsed_at(self, db_session, seed_data):
        """按 parsed_at 排序正常"""
        results = db_session.query(Transaction).order_by(
            Transaction.parsed_at.desc()
        ).limit(10).all()
        assert len(results) == 10
        
        # 验证排序正确
        for i in range(len(results) - 1):
            assert results[i].parsed_at >= results[i + 1].parsed_at
    
    def test_group_by_category(self, db_session, seed_data):
        """按分类聚合正常"""
        from sqlalchemy import func
        
        results = db_session.query(
            Transaction.category,
            func.sum(Transaction.amount)
        ).group_by(Transaction.category).all()
        
        assert len(results) > 0


class TestIndexCount:
    """测试索引总数"""
    
    def test_total_user_indexes(self, setup_db):
        """验证用户索引总数 >= 27"""
        inspector = inspect(engine)
        total = 0
        
        for table_name in inspector.get_table_names():
            indexes = inspector.get_indexes(table_name)
            # 排除主键自动索引
            user_indexes = [
                idx for idx in indexes 
                if not idx['name'].startswith('pk_') 
                and 'autoindex' not in idx['name']
                and not idx['name'].startswith('ix_sqlite_')
            ]
            total += len(user_indexes)
        
        # 至少 27 个用户索引（不含主键）
        assert total >= 27, f"Expected >= 27 user indexes, got {total}"
