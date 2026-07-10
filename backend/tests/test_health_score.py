"""V2-016 五维度评分模型测试"""
import pytest
import sys
import os
import json

# 必须在导入 app 之前设置 DATABASE_URL 为 SQLite
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta

from app.database import Base, get_db, Transaction, Account, Asset, Liability, Setting
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


def _set_budgets(db, budgets):
    s = Setting(key="budgets", value=json.dumps(budgets))
    db.add(s)
    db.commit()


# ===== 1. 空数据场景 =====

class TestEmptyData:
    def test_empty_returns_all_zeros(self, client):
        """无任何数据时，所有维度返回0分"""
        resp = client.get("/reports/health-score")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_score"] == 0
        assert data["grade_code"] == "danger"
        assert data["dimensions"]["savings"]["score"] == 0
        assert data["dimensions"]["risk"]["score"] == 0
        assert data["dimensions"]["budget"]["score"] == 0
        assert data["dimensions"]["structure"]["score"] == 0
        assert data["dimensions"]["investment"]["score"] == 0

    def test_empty_has_suggestions(self, client):
        """空数据时每个维度都有建议"""
        resp = client.get("/reports/health-score")
        data = resp.json()
        for dim_name in ["savings", "risk", "budget", "structure", "investment"]:
            assert "suggestion" in data["dimensions"][dim_name]
            assert len(data["dimensions"][dim_name]["suggestion"]) > 0


# ===== 2. 储蓄能力维度 =====

class TestSavingsDimension:
    def test_high_savings_rate(self, client, db_session):
        """储蓄率≥30% → 25分"""
        _add_tx(db_session, 10000, "工资", "income")
        _add_tx(db_session, 5000, "餐饮", "expense")
        _add_tx(db_session, 1000, "交通", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["savings"]["score"] == 25
        assert data["dimensions"]["savings"]["rate"] == 40.0

    def test_medium_savings_rate(self, client, db_session):
        """储蓄率20-30% → 20分"""
        _add_tx(db_session, 10000, "工资", "income")
        _add_tx(db_session, 7500, "餐饮", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["savings"]["score"] == 20

    def test_low_savings_rate(self, client, db_session):
        """储蓄率10-20% → 15分"""
        _add_tx(db_session, 10000, "工资", "income")
        _add_tx(db_session, 8500, "餐饮", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["savings"]["score"] == 15

    def test_negative_savings_rate(self, client, db_session):
        """储蓄率<0% → 0分"""
        _add_tx(db_session, 5000, "工资", "income")
        _add_tx(db_session, 8000, "餐饮", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["savings"]["score"] == 0
        assert data["dimensions"]["savings"]["rate"] < 0


# ===== 3. 抗风险能力维度 =====

class TestRiskDimension:
    def test_sufficient_emergency_fund(self, client, db_session):
        """应急储备≥6个月 → 25分"""
        _add_account(db_session, "应急基金", "emergency", 60000)
        _add_tx(db_session, 10000, "餐饮", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["risk"]["score"] == 25
        assert data["dimensions"]["risk"]["months"] == 6.0

    def test_moderate_emergency_fund(self, client, db_session):
        """应急储备3-6个月 → 20分"""
        _add_account(db_session, "应急基金", "emergency", 40000)
        _add_tx(db_session, 10000, "餐饮", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["risk"]["score"] == 20

    def test_low_emergency_fund(self, client, db_session):
        """应急储备1-3个月 → 12分"""
        _add_account(db_session, "应急基金", "emergency", 15000)
        _add_tx(db_session, 10000, "餐饮", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["risk"]["score"] == 12

    def test_no_emergency_fund(self, client, db_session):
        """无应急账户 → 0分"""
        _add_account(db_session, "工资卡", "consumption", 5000)
        _add_tx(db_session, 10000, "餐饮", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["risk"]["score"] == 0


# ===== 4. 预算纪律维度 =====

class TestBudgetDimension:
    def test_no_budget(self, client):
        """无预算 → 0分"""
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["budget"]["score"] == 0

    def test_within_budget(self, client, db_session):
        """预算内 → 高分"""
        _set_budgets(db_session, [{"category": "餐饮", "monthly_limit": 3000, "level": "L1"}])
        _add_tx(db_session, 2000, "餐饮", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["budget"]["score"] == 20

    def test_over_budget(self, client, db_session):
        """超预算 → 低分"""
        _set_budgets(db_session, [{"category": "餐饮", "monthly_limit": 1000, "level": "L1"}])
        _add_tx(db_session, 2000, "餐饮", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["budget"]["score"] <= 10


# ===== 5. 支出结构维度 =====

class TestStructureDimension:
    def test_healthy_structure(self, client, db_session):
        """必要支出<50% → 15分"""
        _add_tx(db_session, 3000, "餐饮", "expense")
        _add_tx(db_session, 4000, "娱乐", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["structure"]["score"] == 15
        assert data["dimensions"]["structure"]["necessary_ratio"] < 50

    def test_poor_structure(self, client, db_session):
        """必要支出>80% → 0分"""
        _add_tx(db_session, 9000, "房租", "expense")
        _add_tx(db_session, 1000, "娱乐", "expense")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["structure"]["score"] == 0


# ===== 6. 投资增长维度 =====

class TestInvestmentDimension:
    def test_no_investment(self, client):
        """无投资数据 → 0分"""
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["investment"]["score"] == 0

    def test_investment_with_initial_value(self, client, db_session):
        """有投资且增长 → 高分"""
        _add_asset(db_session, "沪深300基金", "fund", 11000, initial_value=10000)
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["investment"]["score"] >= 12

    def test_investment_loss(self, client, db_session):
        """投资亏损 → 低分"""
        _add_asset(db_session, "股票", "stock", 8000, initial_value=10000)
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["dimensions"]["investment"]["score"] <= 4


# ===== 7. 综合评分 =====

class TestOverallScore:
    def test_perfect_score(self, client, db_session):
        """全维度高分"""
        _add_tx(db_session, 20000, "工资", "income")
        _add_tx(db_session, 3000, "餐饮", "expense")
        _add_tx(db_session, 2000, "娱乐", "expense")
        _add_account(db_session, "应急基金", "emergency", 100000)
        _set_budgets(db_session, [
            {"category": "餐饮", "monthly_limit": 5000, "level": "L1"},
            {"category": "娱乐", "monthly_limit": 3000, "level": "L3"},
        ])
        _add_asset(db_session, "基金", "fund", 12000, initial_value=10000)

        resp = client.get("/reports/health-score")
        data = resp.json()
        assert data["total_score"] >= 75
        assert data["grade_code"] in ["excellent", "healthy"]

    def test_radar_data_normalized(self, client):
        """雷达图数据归一化到 0-1"""
        resp = client.get("/reports/health-score")
        data = resp.json()
        for key, val in data["radar"].items():
            assert 0 <= val <= 1

    def test_top_suggestion_present(self, client):
        """综合建议非空"""
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert len(data["top_suggestion"]) > 0
        assert "最需要改善" in data["top_suggestion"]

    def test_year_month_params(self, client, db_session):
        """支持指定年月"""
        resp = client.get("/reports/health-score?year=2026&month=6")
        data = resp.json()
        assert data["year"] == 2026
        assert data["month"] == 6
        assert data["period"] == "2026年6月"

    def test_data_sources_info(self, client, db_session):
        """返回数据来源统计"""
        _add_tx(db_session, 5000, "工资", "income")
        resp = client.get("/reports/health-score")
        data = resp.json()
        assert "data_sources" in data
        assert data["data_sources"]["transaction_count"] == 1
        assert data["data_sources"]["total_income"] == 5000
