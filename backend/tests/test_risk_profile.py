"""V2-017 风险画像推断测试"""
import pytest
import sys
import os
import json

os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta

from app.database import Base, get_db, Transaction, Account, Asset
from app.main import app

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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _add_tx(db, amount, category, ttype, days_ago=0):
    t = Transaction(
        amount=amount, category=category, account="微信",
        transaction_type=ttype,
        parsed_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.add(t)
    db.commit()
    return t


def _add_account(db, name, purpose, balance, account_type="bank"):
    a = Account(
        name=name, account_type=account_type, purpose=purpose,
        balance=balance, status="active"
    )
    db.add(a)
    db.commit()
    return a


def _add_asset(db, name, asset_type, current_value, initial_value=0):
    a = Asset(
        name=name, asset_type=asset_type, current_value=current_value,
        initial_value=initial_value, status="active"
    )
    db.add(a)
    db.commit()
    return a


# ===== 1. 空数据场景 =====

class TestEmptyData:
    def test_empty_returns_cautious(self, client):
        """无数据时返回谨慎型"""
        resp = client.get("/investment/risk-profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["risk_level"] in ["conservative", "cautious"]
        assert "risk_score" in data
        assert 0 <= data["risk_score"] <= 100

    def test_empty_has_allocation(self, client):
        """空数据也有配置建议"""
        resp = client.get("/investment/risk-profile")
        data = resp.json()
        alloc = data["allocation_suggestion"]
        assert "fixed_income" in alloc
        assert "mixed" in alloc
        assert "equity" in alloc
        assert alloc["fixed_income"] + alloc["mixed"] + alloc["equity"] == 100


# ===== 2. 激进型 =====

class TestAggressive:
    def test_aggressive_profile(self, client, db_session):
        """高纪律+高应急+有投资经验 → 激进型"""
        # 稳定收入+低支出（高储蓄率）
        for i in range(6):
            _add_tx(db_session, 15000, "工资", "income", days_ago=i * 30)
            _add_tx(db_session, 3000, "餐饮", "expense", days_ago=i * 30)
        # 应急充足
        _add_account(db_session, "应急基金", "emergency", 80000)
        # 有投资经验
        _add_account(db_session, "证券账户", "investment", 60000, account_type="stock")
        _add_asset(db_session, "沪深300", "fund", 30000, initial_value=25000)

        resp = client.get("/investment/risk-profile")
        data = resp.json()
        assert data["risk_level"] == "aggressive"
        assert data["risk_emoji"] == "🔥"
        assert data["allocation_suggestion"]["equity"] == 40

    def test_aggressive_horizon(self, client, db_session):
        """激进型投资期限 ≥ 5年"""
        for i in range(6):
            _add_tx(db_session, 15000, "工资", "income", days_ago=i * 30)
            _add_tx(db_session, 3000, "餐饮", "expense", days_ago=i * 30)
        _add_account(db_session, "应急基金", "emergency", 80000)
        _add_account(db_session, "证券", "investment", 60000, account_type="stock")

        resp = client.get("/investment/risk-profile")
        data = resp.json()
        assert "5年" in data["investment_horizon"]


# ===== 3. 稳健型 =====

class TestBalanced:
    def test_balanced_profile(self, client, db_session):
        """消费稳定+应急充足 → 稳健型"""
        for i in range(6):
            _add_tx(db_session, 10000, "工资", "income", days_ago=i * 30)
            _add_tx(db_session, 6000, "餐饮", "expense", days_ago=i * 30)
        _add_account(db_session, "应急基金", "emergency", 40000)

        resp = client.get("/investment/risk-profile")
        data = resp.json()
        assert data["risk_level"] == "balanced"
        assert data["allocation_suggestion"]["equity"] == 20


# ===== 4. 保守型 =====

class TestConservative:
    def test_conservative_low_emergency(self, client, db_session):
        """应急不足 → 保守型"""
        for i in range(6):
            _add_tx(db_session, 10000, "工资", "income", days_ago=i * 30)
            _add_tx(db_session, 8000, "餐饮", "expense", days_ago=i * 30)
        # 无应急账户
        _add_account(db_session, "工资卡", "consumption", 5000)

        resp = client.get("/investment/risk-profile")
        data = resp.json()
        assert data["risk_level"] == "conservative"
        assert data["allocation_suggestion"]["fixed_income"] == 70


# ===== 5. 维度数据 =====

class TestDimensions:
    def test_dimensions_present(self, client, db_session):
        """返回四个维度数据"""
        resp = client.get("/investment/risk-profile")
        data = resp.json()
        dims = data["dimensions"]
        assert "stability" in dims
        assert "emergency" in dims
        assert "discipline" in dims
        assert "experience" in dims

    def test_action_items_present(self, client, db_session):
        """返回行动建议"""
        resp = client.get("/investment/risk-profile")
        data = resp.json()
        assert len(data["action_items"]) > 0

    def test_data_sources(self, client, db_session):
        """返回数据来源"""
        _add_tx(db_session, 10000, "工资", "income")
        resp = client.get("/investment/risk-profile")
        data = resp.json()
        assert data["data_sources"]["total_transactions"] == 1

    def test_allocation_sums_100(self, client, db_session):
        """配置建议总和为100"""
        for i in range(6):
            _add_tx(db_session, 10000, "工资", "income", days_ago=i * 30)
            _add_tx(db_session, 5000, "餐饮", "expense", days_ago=i * 30)
        _add_account(db_session, "应急基金", "emergency", 50000)

        resp = client.get("/investment/risk-profile")
        data = resp.json()
        alloc = data["allocation_suggestion"]
        total = alloc["fixed_income"] + alloc["mixed"] + alloc["equity"]
        assert total == 100


# ===== 6. 投资经验检测 =====

class TestExperience:
    def test_no_investment_experience(self, client, db_session):
        """无投资 → experience_score = 0"""
        resp = client.get("/investment/risk-profile")
        data = resp.json()
        assert data["dimensions"]["experience"]["score"] == 0

    def test_has_investment(self, client, db_session):
        """有投资资产 → experience_score > 0"""
        _add_asset(db_session, "基金", "fund", 20000, initial_value=15000)
        resp = client.get("/investment/risk-profile")
        data = resp.json()
        assert data["dimensions"]["experience"]["score"] >= 1
