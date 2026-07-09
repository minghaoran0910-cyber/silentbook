"""V2-009 现金流日历测试"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from datetime import datetime

from app.database import Base, get_db, Transaction
from app.main import app

# SQLite 内存数据库
SQLALCHEMY_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def setup_transactions(db, txs):
    for tx in txs:
        db.add(Transaction(**tx))
    db.commit()


class TestCashflowCalendar:

    def test_empty_month(self, client):
        """空月份：返回完整日历，全0"""
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7})
        assert response.status_code == 200
        data = response.json()
        
        assert data["year"] == 2026
        assert data["month"] == 7
        assert data["days_in_month"] == 31
        assert len(data["days"]) == 31
        assert data["summary"]["total_income"] == 0
        assert data["summary"]["total_expense"] == 0
        assert data["summary"]["total_net"] == 0
        assert data["summary"]["transaction_count"] == 0
        assert data["summary"]["active_days"] == 0
        for day in data["days"]:
            assert day["income"] == 0
            assert day["expense"] == 0
            assert day["net"] == 0

    def test_with_transactions(self, client, db_session):
        """有交易的月份：正确聚合"""
        setup_transactions(db_session, [
            {"amount": 1000, "category": "工资", "account": "招商", "transaction_type": "income",
             "parsed_at": datetime(2026, 7, 3, 10, 0), "confidence": 1.0},
            {"amount": 200, "category": "餐饮", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 3, 12, 0), "confidence": 1.0},
            {"amount": 50, "category": "交通", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 3, 18, 0), "confidence": 1.0},
            {"amount": 500, "category": "房租", "account": "招商", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 15, 9, 0), "confidence": 1.0},
            {"amount": 3000, "category": "兼职", "account": "支付宝", "transaction_type": "income",
             "parsed_at": datetime(2026, 7, 20, 14, 0), "confidence": 1.0},
        ])
        
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7})
        assert response.status_code == 200
        data = response.json()
        
        assert data["year"] == 2026
        assert data["month"] == 7
        assert len(data["days"]) == 31
        
        day3 = data["days"][2]
        assert day3["day"] == 3
        assert day3["income"] == 1000
        assert day3["expense"] == 250
        assert day3["net"] == 750
        assert day3["transaction_count"] == 3
        
        day15 = data["days"][14]
        assert day15["day"] == 15
        assert day15["income"] == 0
        assert day15["expense"] == 500
        assert day15["net"] == -500
        assert day15["transaction_count"] == 1
        
        day20 = data["days"][19]
        assert day20["day"] == 20
        assert day20["income"] == 3000
        assert day20["expense"] == 0
        assert day20["net"] == 3000
        assert day20["transaction_count"] == 1
        
        day1 = data["days"][0]
        assert day1["income"] == 0
        assert day1["expense"] == 0
        assert day1["net"] == 0
        assert day1["transaction_count"] == 0
        
        assert data["summary"]["total_income"] == 4000
        assert data["summary"]["total_expense"] == 750
        assert data["summary"]["total_net"] == 3250
        assert data["summary"]["transaction_count"] == 5
        assert data["summary"]["active_days"] == 3
        assert data["summary"]["avg_daily_expense"] == round(750 / 31, 2)

    def test_default_current_month(self, client):
        """不传 year/month：默认当前月"""
        response = client.get("/cashflow/calendar")
        assert response.status_code == 200
        data = response.json()
        now = datetime.utcnow()
        assert data["year"] == now.year
        assert data["month"] == now.month

    def test_account_filter(self, client, db_session):
        """按账户筛选"""
        setup_transactions(db_session, [
            {"amount": 100, "category": "餐饮", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 5, 10, 0), "confidence": 1.0},
            {"amount": 200, "category": "餐饮", "account": "招商", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 5, 11, 0), "confidence": 1.0},
        ])
        
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7, "account": "微信"})
        assert response.status_code == 200
        data = response.json()
        
        assert data["account"] == "微信"
        assert data["summary"]["total_expense"] == 100
        assert data["summary"]["transaction_count"] == 1

    def test_weekday_correctness(self, client):
        """验证 weekday 字段正确"""
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7})
        data = response.json()
        # 2026-07-01 是周三（weekday=2）
        assert data["days"][0]["weekday"] == 2
        # 2026-07-04 是周六（weekday=5）
        assert data["days"][3]["weekday"] == 5

    def test_february_normal(self, client):
        """2026年2月：28天"""
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 2})
        assert response.status_code == 200
        data = response.json()
        assert data["days_in_month"] == 28
        assert len(data["days"]) == 28

    def test_february_leap_year(self, client):
        """2028年2月闰年：29天"""
        response = client.get("/cashflow/calendar", params={"year": 2028, "month": 2})
        assert response.status_code == 200
        data = response.json()
        assert data["days_in_month"] == 29
        assert len(data["days"]) == 29

    def test_cross_month_transactions(self, client, db_session):
        """跨月交易不串月"""
        setup_transactions(db_session, [
            {"amount": 999, "category": "测试", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 6, 30, 23, 59), "confidence": 1.0},
            {"amount": 100, "category": "餐饮", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 1, 0, 1), "confidence": 1.0},
            {"amount": 888, "category": "测试", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 8, 1, 0, 0), "confidence": 1.0},
        ])
        
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7})
        data = response.json()
        
        assert data["summary"]["total_expense"] == 100
        assert data["summary"]["transaction_count"] == 1

    def test_net_calculation(self, client, db_session):
        """净现金流计算：收入-支出"""
        setup_transactions(db_session, [
            {"amount": 5000, "category": "工资", "account": "招商", "transaction_type": "income",
             "parsed_at": datetime(2026, 7, 10, 10, 0), "confidence": 1.0},
            {"amount": 3000, "category": "房租", "account": "招商", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 10, 11, 0), "confidence": 1.0},
        ])
        
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7})
        data = response.json()
        
        day10 = data["days"][9]
        assert day10["income"] == 5000
        assert day10["expense"] == 3000
        assert day10["net"] == 2000
        assert data["summary"]["total_net"] == 2000

    def test_transfer_transactions_included(self, client, db_session):
        """转账交易也计入现金流"""
        setup_transactions(db_session, [
            {"amount": 500, "category": "转账", "account": "招商", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 5, 10, 0), "confidence": 1.0},
            {"amount": 500, "category": "转账", "account": "支付宝", "transaction_type": "income",
             "parsed_at": datetime(2026, 7, 5, 10, 0), "confidence": 1.0},
        ])
        
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7})
        data = response.json()
        
        assert data["summary"]["total_income"] == 500
        assert data["summary"]["total_expense"] == 500
        assert data["summary"]["total_net"] == 0

    def test_day_fields_sequential(self, client):
        """验证每天的 day 字段从1开始递增"""
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7})
        data = response.json()
        for i, day in enumerate(data["days"]):
            assert day["day"] == i + 1
            assert day["date"] == f"2026-07-{i+1:02d}"

    def test_same_day_multiple_transactions(self, client, db_session):
        """同日多笔交易正确聚合"""
        setup_transactions(db_session, [
            {"amount": 100, "category": "餐饮", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 10, 8, 0), "confidence": 1.0},
            {"amount": 50, "category": "交通", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 10, 9, 0), "confidence": 1.0},
            {"amount": 200, "category": "餐饮", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 10, 12, 0), "confidence": 1.0},
            {"amount": 5000, "category": "工资", "account": "招商", "transaction_type": "income",
             "parsed_at": datetime(2026, 7, 10, 18, 0), "confidence": 1.0},
        ])
        
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7})
        data = response.json()
        
        day10 = data["days"][9]
        assert day10["income"] == 5000
        assert day10["expense"] == 350
        assert day10["net"] == 4650
        assert day10["transaction_count"] == 4

    def test_no_account_filter_returns_all(self, client, db_session):
        """不传 account 参数：返回所有账户的交易"""
        setup_transactions(db_session, [
            {"amount": 100, "category": "餐饮", "account": "微信", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 5, 10, 0), "confidence": 1.0},
            {"amount": 200, "category": "餐饮", "account": "招商", "transaction_type": "expense",
             "parsed_at": datetime(2026, 7, 5, 11, 0), "confidence": 1.0},
            {"amount": 300, "category": "兼职", "account": "支付宝", "transaction_type": "income",
             "parsed_at": datetime(2026, 7, 5, 12, 0), "confidence": 1.0},
        ])
        
        response = client.get("/cashflow/calendar", params={"year": 2026, "month": 7})
        data = response.json()
        
        assert data["account"] is None
        assert data["summary"]["total_expense"] == 300
        assert data["summary"]["total_income"] == 300
        assert data["summary"]["transaction_count"] == 3
