"""V2-028: 下月支出预测测试"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, Transaction, RecurringTransaction, get_db

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def _add_tx(db, category, amount, days_ago=0, tx_type="expense", account="default"):
    tx = Transaction(category=category, amount=amount, account=account,
                     transaction_type=tx_type,
                     parsed_at=datetime.now() - timedelta(days=days_ago))
    db.add(tx)
    db.commit()

class TestNextMonthForecast:
    def test_empty_data(self):
        r = client.get("/forecast/next-month")
        assert r.status_code == 200
        data = r.json()
        assert "total_predicted" in data
        assert data["total_predicted"] == 0

    def test_basic_forecast(self):
        with TestingSessionLocal() as db:
            for i in range(3):
                _add_tx(db, "餐饮", 30, days_ago=i*7)
        r = client.get("/forecast/next-month")
        assert r.status_code == 200
        data = r.json()
        assert data["total_predicted"] > 0

    def test_category_breakdown(self):
        with TestingSessionLocal() as db:
            _add_tx(db, "餐饮", 50, days_ago=1)
            _add_tx(db, "交通", 20, days_ago=2)
        r = client.get("/forecast/next-month")
        data = r.json()
        assert "categories" in data
        assert len(data["categories"]) >= 2

    def test_trend_detection(self):
        with TestingSessionLocal() as db:
            for i in range(4):
                _add_tx(db, "餐饮", 100 + i*20, days_ago=i*7)
        r = client.get("/forecast/next-month")
        data = r.json()
        assert "categories" in data

    def test_recurring_integration(self):
        with TestingSessionLocal() as db:
            recurring = RecurringTransaction(
                name="房租", amount=3000, category="住房",
                frequency="monthly", day_of_month=1, transaction_type="expense", is_active=True)
            db.add(recurring)
            db.commit()
        r = client.get("/forecast/next-month")
        data = r.json()
        assert "total_predicted" in data

    def test_comparison(self):
        with TestingSessionLocal() as db:
            for i in range(7):
                _add_tx(db, "餐饮", 40, days_ago=i*3)
        r = client.get("/forecast/next-month")
        data = r.json()
        assert "comparison" in data

    def test_confidence_levels(self):
        with TestingSessionLocal() as db:
            _add_tx(db, "餐饮", 50, days_ago=1)
        r = client.get("/forecast/next-month")
        data = r.json()
        assert "confidence" in data

    def test_account_filter(self):
        with TestingSessionLocal() as db:
            _add_tx(db, "餐饮", 50, days_ago=1, account="wechat")
            _add_tx(db, "餐饮", 30, days_ago=2, account="alipay")
        r = client.get("/forecast/next-month?account=wechat")
        data = r.json()
        assert data["total_predicted"] > 0

    def test_no_negative_prediction(self):
        with TestingSessionLocal() as db:
            _add_tx(db, "退款", 50, days_ago=1, tx_type="income")
        r = client.get("/forecast/next-month")
        data = r.json()
        assert data["total_predicted"] >= 0

    def test_forecast_month_field(self):
        with TestingSessionLocal() as db:
            _add_tx(db, "餐饮", 30, days_ago=1)
        r = client.get("/forecast/next-month")
        data = r.json()
        assert "forecast_month" in data

    def test_recurring_items_field(self):
        with TestingSessionLocal() as db:
            recurring = RecurringTransaction(
                name="会员", amount=30, category="娱乐",
                frequency="monthly", day_of_month=15, transaction_type="expense", is_active=True)
            db.add(recurring)
            db.commit()
        r = client.get("/forecast/next-month")
        data = r.json()
        assert "recurring_items" in data
        assert "recurring_items" in data
