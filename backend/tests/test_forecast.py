"""V2-010 现金流预测测试"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from datetime import datetime, timedelta

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


class TestCashflowForecast:

    def test_empty_data(self, client):
        """无历史数据：返回全0预测，置信度low"""
        response = client.get("/cashflow/forecast")
        assert response.status_code == 200
        data = response.json()
        
        assert data["forecast_days"] == 30
        assert data["summary"]["predicted_total_income"] == 0
        assert data["summary"]["predicted_total_expense"] == 0
        assert data["summary"]["predicted_net"] == 0
        assert data["summary"]["confidence"] == "low"
        assert data["summary"]["history_transaction_count"] == 0
        assert data["summary"]["recurring_count"] == 0
        assert len(data["daily_forecast"]) == 0
        assert data["recurring_items"] == []

    def test_forecast_days_param(self, client, db_session):
        """自定义预测天数"""
        now = datetime.utcnow()
        # 添加足够多的交易以获得medium置信度
        for i in range(25):
            db_session.add(Transaction(
                amount=50, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"days": 7})
        assert response.status_code == 200
        data = response.json()
        assert data["forecast_days"] == 7
        assert len(data["daily_forecast"]) == 7

    def test_recurring_detection(self, client, db_session):
        """检测固定收支：同分类+相似金额+跨月"""
        now = datetime.utcnow()
        # 工资：连续3个月15号
        for months_ago in range(3):
            d = now - timedelta(days=months_ago * 30 + 15)
            db_session.add(Transaction(
                amount=10000, category="工资", account="招商",
                transaction_type="income", confidence=1.0,
                parsed_at=d
            ))
        # 房租：连续3个月1号
        for months_ago in range(3):
            d = now - timedelta(days=months_ago * 30 + 1)
            db_session.add(Transaction(
                amount=3000, category="房租", account="招商",
                transaction_type="expense", confidence=1.0,
                parsed_at=d
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"history_days": 120})
        assert response.status_code == 200
        data = response.json()
        
        # 应检测到2个固定项
        assert data["summary"]["recurring_count"] == 2
        recurring_cats = [item["category"] for item in data["recurring_items"]]
        assert "工资" in recurring_cats
        assert "房租" in recurring_cats

    def test_non_recurring_daily_average(self, client, db_session):
        """非固定收支按日均摊到每天"""
        now = datetime.utcnow()
        # 90天内总共花费2700元餐饮（非固定，因为每月金额差异大）
        for i in range(90):
            db_session.add(Transaction(
                amount=30, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"history_days": 90, "days": 10})
        assert response.status_code == 200
        data = response.json()
        
        # 日均 = 2700 / 90 = 30
        assert data["summary"]["avg_daily_expense"] == 30.0
        # 每天预测支出至少包含日均30
        for day in data["daily_forecast"]:
            assert day["predicted_expense"] >= 30.0

    def test_recurring_placed_on_correct_day(self, client, db_session):
        """固定收支放在正确的日期"""
        now = datetime.utcnow()
        # 工资在每月15号
        for months_ago in range(3):
            d = now.replace(day=15) - timedelta(days=months_ago * 30)
            if d > now:
                d = d - timedelta(days=30)
            db_session.add(Transaction(
                amount=5000, category="工资", account="招商",
                transaction_type="income", confidence=1.0,
                parsed_at=d
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"history_days": 120, "days": 31})
        assert response.status_code == 200
        data = response.json()
        
        # 找到15号的那天
        day_15 = [d for d in data["daily_forecast"] if d["day"] == 15]
        if day_15:
            # 15号应该有固定收入5000
            assert day_15[0]["recurring_income"] == 5000.0

    def test_confidence_low(self, client, db_session):
        """少量数据：置信度low"""
        now = datetime.utcnow()
        for i in range(5):
            db_session.add(Transaction(
                amount=50, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"history_days": 10})
        data = response.json()
        assert data["summary"]["confidence"] == "low"

    def test_confidence_medium(self, client, db_session):
        """中等数据量：置信度medium"""
        now = datetime.utcnow()
        for i in range(25):
            db_session.add(Transaction(
                amount=50, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"history_days": 30})
        data = response.json()
        assert data["summary"]["confidence"] == "medium"

    def test_confidence_high(self, client, db_session):
        """大量数据：置信度high"""
        now = datetime.utcnow()
        for i in range(60):
            db_session.add(Transaction(
                amount=50, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"history_days": 90})
        data = response.json()
        assert data["summary"]["confidence"] == "high"

    def test_account_filter(self, client, db_session):
        """按账户筛选预测"""
        now = datetime.utcnow()
        for i in range(20):
            db_session.add(Transaction(
                amount=100, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
            db_session.add(Transaction(
                amount=200, category="餐饮", account="招商",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"account": "微信", "history_days": 30})
        assert response.status_code == 200
        data = response.json()
        
        assert data["account"] == "微信"
        # 日均应为 100*20/30 ≈ 66.67
        assert data["summary"]["avg_daily_expense"] > 60
        assert data["summary"]["avg_daily_expense"] < 70

    def test_forecast_starts_from_tomorrow(self, client, db_session):
        """预测从明天开始"""
        now = datetime.utcnow()
        db_session.add(Transaction(
            amount=100, category="test", account="微信",
            transaction_type="expense", confidence=1.0,
            parsed_at=now
        ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"days": 3, "history_days": 5})
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["daily_forecast"]) == 3
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        assert data["daily_forecast"][0]["date"] == tomorrow

    def test_daily_forecast_fields(self, client, db_session):
        """验证每日预测包含所有必要字段"""
        now = datetime.utcnow()
        for i in range(10):
            db_session.add(Transaction(
                amount=50, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"days": 5, "history_days": 15})
        data = response.json()
        
        assert len(data["daily_forecast"]) == 5
        for day in data["daily_forecast"]:
            assert "date" in day
            assert "day" in day
            assert "weekday" in day
            assert "predicted_income" in day
            assert "predicted_expense" in day
            assert "predicted_net" in day
            assert "recurring_income" in day
            assert "recurring_expense" in day

    def test_summary_fields(self, client, db_session):
        """验证汇总字段完整性"""
        now = datetime.utcnow()
        for i in range(10):
            db_session.add(Transaction(
                amount=50, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"days": 5, "history_days": 15})
        data = response.json()
        
        s = data["summary"]
        assert "predicted_total_income" in s
        assert "predicted_total_expense" in s
        assert "predicted_net" in s
        assert "avg_daily_income" in s
        assert "avg_daily_expense" in s
        assert "recurring_count" in s
        assert "confidence" in s
        assert "history_transaction_count" in s

    def test_recurring_with_variable_amount(self, client, db_session):
        """固定收支金额有小波动（5%内）仍应被识别"""
        now = datetime.utcnow()
        amounts = [3000, 3100, 2950]  # 波动 < 5%
        for i, amt in enumerate(amounts):
            d = now - timedelta(days=i * 30 + 5)
            db_session.add(Transaction(
                amount=amt, category="房租", account="招商",
                transaction_type="expense", confidence=1.0,
                parsed_at=d
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"history_days": 120})
        data = response.json()
        
        assert data["summary"]["recurring_count"] == 1
        item = data["recurring_items"][0]
        assert item["category"] == "房租"
        # 平均金额
        assert 2950 <= item["amount"] <= 3100

    def test_non_recurring_not_detected_as_recurring(self, client, db_session):
        """金额差异大的同分类交易不应被识别为固定"""
        now = datetime.utcnow()
        # 同分类但金额差异大
        for i in range(3):
            db_session.add(Transaction(
                amount=10 + i * 500, category="购物", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i * 30 + 10)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"history_days": 120})
        data = response.json()
        
        # 不应检测到固定项
        assert data["summary"]["recurring_count"] == 0

    def test_income_and_expense_forecast(self, client, db_session):
        """同时预测收入和支出"""
        now = datetime.utcnow()
        for i in range(30):
            db_session.add(Transaction(
                amount=100, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
            db_session.add(Transaction(
                amount=300, category="兼职", account="支付宝",
                transaction_type="income", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"days": 10, "history_days": 30})
        data = response.json()
        
        # 日均收入 = 300*30/30 = 300
        assert data["summary"]["avg_daily_income"] == 300.0
        # 日均支出 = 100*30/30 = 100
        assert data["summary"]["avg_daily_expense"] == 100.0
        # 每天净 = 300 - 100 = 200
        for day in data["daily_forecast"]:
            assert day["predicted_net"] == 200.0

    def test_total_calculation(self, client, db_session):
        """汇总金额 = 每日之和"""
        now = datetime.utcnow()
        for i in range(20):
            db_session.add(Transaction(
                amount=50, category="餐饮", account="微信",
                transaction_type="expense", confidence=1.0,
                parsed_at=now - timedelta(days=i)
            ))
        db_session.commit()
        
        response = client.get("/cashflow/forecast", params={"days": 10, "history_days": 25})
        data = response.json()
        
        total_from_daily = sum(d["predicted_expense"] for d in data["daily_forecast"])
        assert abs(data["summary"]["predicted_total_expense"] - total_from_daily) < 0.1

    def test_history_days_param(self, client, db_session):
        """自定义回溯天数"""
        now = datetime.utcnow()
        # 10天前: 100元
        db_session.add(Transaction(
            amount=100, category="test", account="微信",
            transaction_type="expense", confidence=1.0,
            parsed_at=now - timedelta(days=10)
        ))
        # 50天前: 200元
        db_session.add(Transaction(
            amount=200, category="test", account="微信",
            transaction_type="expense", confidence=1.0,
            parsed_at=now - timedelta(days=50)
        ))
        db_session.commit()
        
        # 回溯30天：只看到100元那笔
        response = client.get("/cashflow/forecast", params={"history_days": 30, "days": 5})
        data = response.json()
        assert data["summary"]["history_transaction_count"] == 1
        
        # 回溯60天：看到两笔
        response = client.get("/cashflow/forecast", params={"history_days": 60, "days": 5})
        data = response.json()
        assert data["summary"]["history_transaction_count"] == 2
