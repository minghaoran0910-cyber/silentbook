"""V2-018 资产配置建议测试"""
import pytest
import sys
import os

os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, Account, Asset
from app.main import app

engine = create_engine(
    "sqlite://",
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


# ===== 1. 无投资数据 =====

class TestNoInvestment:
    def test_no_investment(self, client):
        """无投资数据时返回建议配置"""
        resp = client.get("/investment/allocation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_investment"] is False
        assert "suggested_allocation" in data

    def test_no_investment_has_suggestion(self, client):
        """无投资时也有消息提示"""
        resp = client.get("/investment/allocation")
        data = resp.json()
        assert len(data["message"]) > 0


# ===== 2. 有投资数据 =====

class TestWithInvestment:
    def test_with_investment(self, client, db_session):
        """有投资数据时返回配置分析"""
        _add_asset(db_session, "债券基金", "bond", 30000)
        _add_asset(db_session, "沪深300", "fund", 20000)
        _add_asset(db_session, "股票", "stock", 10000)

        resp = client.get("/investment/allocation")
        data = resp.json()
        assert data["has_investment"] is True
        assert data["total_investment"] == 60000

    def test_allocation_sums_to_100(self, client, db_session):
        """当前配置百分比总和接近100"""
        _add_asset(db_session, "债券", "bond", 50000)
        _add_asset(db_session, "基金", "fund", 30000)
        _add_asset(db_session, "股票", "stock", 20000)

        resp = client.get("/investment/allocation")
        data = resp.json()
        total_pct = sum(v["pct"] for v in data["current_allocation"].values())
        assert 99 <= total_pct <= 101

    def test_deviation_present(self, client, db_session):
        """返回偏离度数据"""
        _add_asset(db_session, "债券", "bond", 50000)
        _add_asset(db_session, "股票", "stock", 50000)

        resp = client.get("/investment/allocation")
        data = resp.json()
        assert "deviation" in data
        assert "fixed_income" in data["deviation"]
        assert "equity" in data["deviation"]


# ===== 3. 再平衡提醒 =====

class TestRebalance:
    def test_rebalance_alert_triggered(self, client, db_session):
        """偏离 > 5% 触发再平衡提醒"""
        # 全部股票（权益类超配）
        _add_asset(db_session, "股票A", "stock", 40000)
        _add_asset(db_session, "股票B", "stock", 40000)
        _add_account(db_session, "应急基金", "emergency", 30000)

        resp = client.get("/investment/allocation")
        data = resp.json()
        # 权益类应该超配
        if data["needs_rebalance"]:
            assert len(data["rebalance_alerts"]) > 0

    def test_no_rebalance_when_balanced(self, client, db_session):
        """配置接近目标时不触发提醒"""
        # 均衡配置
        _add_asset(db_session, "债券", "bond", 50000)
        _add_asset(db_session, "基金", "fund", 30000)
        _add_asset(db_session, "股票", "stock", 20000)
        _add_account(db_session, "应急基金", "emergency", 30000)

        resp = client.get("/investment/allocation")
        data = resp.json()
        assert "needs_rebalance" in data


# ===== 4. 风险等级 =====

class TestRiskLevel:
    def test_risk_level_present(self, client, db_session):
        """返回风险等级"""
        _add_asset(db_session, "基金", "fund", 10000)
        resp = client.get("/investment/allocation")
        data = resp.json()
        assert data["risk_level"] in ["aggressive", "balanced", "cautious", "conservative"]

    def test_target_allocation_present(self, client, db_session):
        """返回目标配置"""
        _add_asset(db_session, "基金", "fund", 10000)
        resp = client.get("/investment/allocation")
        data = resp.json()
        assert "target_allocation" in data
        target = data["target_allocation"]
        assert "fixed_income" in target
        assert "mixed" in target
        assert "equity" in target


# ===== 5. 建议 =====

class TestSuggestion:
    def test_suggestion_present(self, client, db_session):
        """返回配置建议"""
        _add_asset(db_session, "基金", "fund", 10000)
        resp = client.get("/investment/allocation")
        data = resp.json()
        assert "suggestion" in data
        assert len(data["suggestion"]) > 0
