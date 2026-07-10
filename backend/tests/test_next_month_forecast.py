"""V2-028: 下月支出预测测试"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, Transaction, RecurringTransaction, get_db


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///test_next_month_forecast.db")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        import os
        os.remove("test_next_month_forecast.db")


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add_expense(db, category, amount, days_ago, tx_type="expense"):
    tx = Transaction(
        amount=amount,
        category=category,
        account="测试账户",
        description=f"{category}支出",
        transaction_type=tx_type,
        parsed_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.add(tx)
    db.commit()


class TestNextMonthForecast:
    """下月支出预测"""
    
    def test_empty_data(self, client):
        """无数据时返回零值"""
        resp = client.get("/forecast/next-month")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_predicted"] == 0
        assert data["categories"] == []
        assert data["confidence"] == "low"
        assert data["history_months"] == 0
    
    def test_basic_forecast(self, client, db_session):
        """有历史数据时能生成预测"""
        # 添加3个月的餐饮数据（每月约1000元）
        for month_offset in range(3):
            days = 30 * (2 - month_offset) + 5
            _add_expense(db_session, "餐饮", 1000, days)
        
        resp = client.get("/forecast/next-month")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_predicted"] > 0
        assert len(data["categories"]) > 0
        assert data["forecast_month"]  # 有预测月份
    
    def test_category_breakdown(self, client, db_session):
        """按分类返回预测明细"""
        # 餐饮：稳定
        for m in range(4):
            _add_expense(db_session, "餐饮", 1000, 30 * (3 - m) + 5)
        # 交通：增长趋势（ oldest=200, newest=500）
        for m, amt in enumerate([200, 300, 400, 500]):
            _add_expense(db_session, "交通", amt, 30 * (3 - m) + 10)
        
        resp = client.get("/forecast/next-month")
        data = resp.json()
        
        cats = {c["category"]: c for c in data["categories"]}
        assert "餐饮" in cats
        assert "交通" in cats
        # 交通应该显示增长趋势
        assert cats["交通"]["trend"] == "increasing"
    
    def test_trend_detection(self, client, db_session):
        """能检测到增长/下降/稳定趋势"""
        # 稳定：每月1000（oldest→newest 都是1000）
        for m in range(4):
            _add_expense(db_session, "稳定类", 1000, 30 * (3 - m) + 5)
        # 增长：oldest=500 → newest=1400
        for m, amt in enumerate([500, 800, 1100, 1400]):
            _add_expense(db_session, "增长类", amt, 30 * (3 - m) + 10)
        # 下降：oldest=2000 → newest=500
        for m, amt in enumerate([2000, 1500, 1000, 500]):
            _add_expense(db_session, "下降类", amt, 30 * (3 - m) + 15)
        
        resp = client.get("/forecast/next-month")
        data = resp.json()
        
        cats = {c["category"]: c for c in data["categories"]}
        assert cats["稳定类"]["trend"] == "stable"
        assert cats["增长类"]["trend"] == "increasing"
        assert cats["下降类"]["trend"] == "decreasing"
    
    def test_recurring_integration(self, client, db_session):
        """固定收支合并到预测"""
        # 添加一些历史数据
        _add_expense(db_session, "餐饮", 500, 10)
        
        # 添加固定支出
        rt = RecurringTransaction(
            name="房租",
            amount=3000,
            category="住房",
            transaction_type="expense",
            frequency="monthly",
            day_of_month=1,
            is_active=True,
        )
        db_session.add(rt)
        db_session.commit()
        
        resp = client.get("/forecast/next-month")
        data = resp.json()
        
        # 应该有房租在 recurring_items 中
        assert len(data["recurring_items"]) > 0
        assert data["recurring_items"][0]["name"] == "房租"
        # 总额应包含房租
        assert data["total_predicted"] >= 3000
    
    def test_comparison(self, client, db_session):
        """返回与本月/上月的对比"""
        # 上月数据
        _add_expense(db_session, "餐饮", 1000, 35)
        # 本月数据
        _add_expense(db_session, "餐饮", 1200, 5)
        
        resp = client.get("/forecast/next-month")
        data = resp.json()
        
        assert "comparison" in data
        assert "current_month" in data["comparison"]
        assert "last_month" in data["comparison"]
        assert "predicted_vs_last_change" in data["comparison"]
    
    def test_confidence_levels(self, client, db_session):
        """数据量影响置信度"""
        # 只有1个月数据 → low
        _add_expense(db_session, "餐饮", 1000, 5)
        
        resp = client.get("/forecast/next-month")
        data = resp.json()
        assert data["confidence"] == "low"
    
    def test_account_filter(self, client, db_session):
        """支持按账户筛选"""
        _add_expense(db_session, "餐饮", 1000, 5)
        tx = Transaction(
            amount=2000, category="购物", account="其他账户",
            description="购物", transaction_type="expense",
            parsed_at=datetime.utcnow() - timedelta(days=10),
        )
        db_session.add(tx)
        db_session.commit()
        
        resp = client.get("/forecast/next-month?account=测试账户")
        data = resp.json()
        cats = [c["category"] for c in data["categories"]]
        assert "购物" not in cats
    
    def test_no_negative_prediction(self, client, db_session):
        """预测金额不能为负"""
        # 急剧下降趋势（oldest=10000 → newest=100）
        for m, amt in enumerate([10000, 5000, 1000, 100]):
            _add_expense(db_session, "暴降类", amt, 30 * (3 - m) + 5)
        
        resp = client.get("/forecast/next-month")
        data = resp.json()
        
        for cat in data["categories"]:
            assert cat["predicted_amount"] >= 0
    
    def test_history_included(self, client, db_session):
        """每个分类包含历史月度数据"""
        for m in range(3):
            _add_expense(db_session, "餐饮", 800 + m * 100, 30 * (2 - m) + 5)
        
        resp = client.get("/forecast/next-month")
        data = resp.json()
        
        cat = data["categories"][0]
        assert "history" in cat
        assert len(cat["history"]) >= 2
    
    def test_trend_summary(self, client, db_session):
        """返回趋势汇总"""
        for m in range(3):
            _add_expense(db_session, "A", 1000, 30 * (2 - m) + 5)
            _add_expense(db_session, "B", 500 + m * 200, 30 * (2 - m) + 10)
        
        resp = client.get("/forecast/next-month")
        data = resp.json()
        
        assert "trend_summary" in data
        ts = data["trend_summary"]
        assert "increasing" in ts
        assert "stable" in ts
        assert "decreasing" in ts
        assert sum(ts.values()) == len(data["categories"])
