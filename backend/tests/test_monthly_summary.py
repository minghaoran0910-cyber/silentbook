"""V2-013 月度财务摘要测试"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime

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
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_tx(db, amount, category, tx_type, day, month=7, year=2026):
    """快捷添加交易"""
    db.add(Transaction(
        amount=amount,
        category=category,
        account="测试账户",
        transaction_type=tx_type,
        parsed_at=datetime(year, month, day, 12, 0),
        confidence=1.0,
    ))


class TestMonthlySummary:

    def test_empty_month(self, client):
        """空月份：所有指标应为 0"""
        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_income"] == 0
        assert data["total_expense"] == 0
        assert data["net_balance"] == 0
        assert data["savings_rate"] == 0
        assert data["transaction_count"] == 0
        assert data["current_net_worth"] == 0
        assert data["net_worth_change"] == 0
        assert data["top_expenses"] == []
        assert data["top_incomes"] == []
        assert data["budget_execution"] == []
        assert data["liability_summary"]["count"] == 0

    def test_basic_income_expense(self, client, db_session):
        """基本收支：收入10000，支出6000"""
        add_tx(db_session, 10000, "工资", "income", 5)
        add_tx(db_session, 3000, "房租", "expense", 6)
        add_tx(db_session, 2000, "餐饮", "expense", 10)
        add_tx(db_session, 1000, "交通", "expense", 15)
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_income"] == 10000
        assert data["total_expense"] == 6000
        assert data["net_balance"] == 4000
        assert data["savings_rate"] == 40.0
        assert data["transaction_count"] == 4

    def test_savings_rate_zero_income(self, client, db_session):
        """零收入时储蓄率应为0"""
        add_tx(db_session, 500, "餐饮", "expense", 1)
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["savings_rate"] == 0

    def test_net_worth_calculation(self, client, db_session):
        """净资产 = 账户余额 + 资产 - 负债"""
        db_session.add(Account(name="招行", account_type="bank", purpose="consumption", balance=5000))
        db_session.add(Account(name="余额宝", account_type="alipay", purpose="emergency", balance=10000))
        db_session.add(Asset(name="基金", asset_type="fund", current_value=20000))
        db_session.add(Liability(name="花呗", liability_type="huabei", current_amount=3000, monthly_payment=500))
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        # 净资产 = 5000 + 10000 + 20000 - 3000 = 32000
        assert data["current_net_worth"] == 32000

    def test_net_worth_change_equals_net_balance(self, client, db_session):
        """净资产变化 = 本月净收支"""
        add_tx(db_session, 8000, "工资", "income", 5)
        add_tx(db_session, 3000, "房租", "expense", 6)
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        assert data["net_worth_change"] == 5000  # 8000 - 3000

    def test_account_summary(self, client, db_session):
        """四账户体系概览"""
        db_session.add(Account(name="招行", account_type="bank", purpose="consumption", balance=3000))
        db_session.add(Account(name="微信", account_type="wechat", purpose="consumption", balance=2000))
        db_session.add(Account(name="余额宝", account_type="alipay", purpose="emergency", balance=15000))
        db_session.add(Account(name="基金账户", account_type="fund", purpose="investment", balance=8000))
        db_session.add(Account(name="定期", account_type="bank", purpose="goal", balance=5000))
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        summary = data["account_summary"]
        assert summary["total_balance"] == 33000
        assert summary["by_purpose"]["consumption"]["count"] == 2
        assert summary["by_purpose"]["consumption"]["total_balance"] == 5000
        assert summary["by_purpose"]["emergency"]["total_balance"] == 15000
        assert summary["by_purpose"]["investment"]["total_balance"] == 8000
        assert summary["by_purpose"]["goal"]["total_balance"] == 5000

    def test_budget_execution(self, client, db_session):
        """预算执行情况"""
        budgets = [
            {"category": "房租", "monthly_limit": 3000, "level": "L1", "alert_threshold": 0.9},
            {"category": "餐饮", "monthly_limit": 2000, "level": "L1", "alert_threshold": 0.9},
            {"category": "娱乐", "monthly_limit": 500, "level": "L3", "alert_threshold": 0.8},
        ]
        db_session.add(Setting(key="budgets", value=json.dumps(budgets)))
        add_tx(db_session, 3000, "房租", "expense", 6)
        add_tx(db_session, 1500, "餐饮", "expense", 10)
        add_tx(db_session, 600, "娱乐", "expense", 15)  # 超预算
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        budgets_data = data["budget_execution"]
        assert len(budgets_data) == 3

        rent = next(b for b in budgets_data if b["category"] == "房租")
        assert rent["budget_limit"] == 3000
        assert rent["actual_spent"] == 3000
        assert rent["usage_rate"] == 100.0
        assert rent["remaining"] == 0

        food = next(b for b in budgets_data if b["category"] == "餐饮")
        assert food["actual_spent"] == 1500
        assert food["usage_rate"] == 75.0
        assert food["remaining"] == 500

        fun = next(b for b in budgets_data if b["category"] == "娱乐")
        assert fun["actual_spent"] == 600
        assert fun["usage_rate"] == 120.0
        assert fun["remaining"] == -100

    def test_liability_summary(self, client, db_session):
        """负债概览"""
        db_session.add(Liability(name="房贷", liability_type="mortgage", current_amount=500000, monthly_payment=3000))
        db_session.add(Liability(name="花呗", liability_type="huabei", current_amount=2000, monthly_payment=500))
        db_session.add(Liability(name="信用卡", liability_type="credit_card", current_amount=5000, monthly_payment=1000, status="active"))
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        liab = data["liability_summary"]
        assert liab["count"] == 3
        assert liab["total_debt"] == 507000
        assert liab["monthly_payment"] == 4500

    def test_top_expenses(self, client, db_session):
        """支出分类排序"""
        add_tx(db_session, 3000, "房租", "expense", 6)
        add_tx(db_session, 2000, "餐饮", "expense", 10)
        add_tx(db_session, 1000, "交通", "expense", 15)
        add_tx(db_session, 500, "娱乐", "expense", 20)
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        expenses = data["top_expenses"]
        assert len(expenses) == 4
        assert expenses[0]["category"] == "房租"
        assert expenses[0]["amount"] == 3000
        assert expenses[0]["percentage"] == 46.2  # 3000/6500

    def test_top_incomes(self, client, db_session):
        """收入分类排序"""
        add_tx(db_session, 10000, "工资", "income", 5)
        add_tx(db_session, 2000, "兼职", "income", 10)
        add_tx(db_session, 500, "理财收益", "income", 15)
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        incomes = data["top_incomes"]
        assert len(incomes) == 3
        assert incomes[0]["category"] == "工资"
        assert incomes[0]["amount"] == 10000

    def test_period_string(self, client):
        """period 字段格式"""
        resp = client.get("/reports/monthly-summary?year=2026&month=3")
        data = resp.json()
        assert data["period"] == "2026年3月"

    def test_default_month(self, client):
        """不传年月时默认当前月"""
        resp = client.get("/reports/monthly-summary")
        assert resp.status_code == 200
        now = datetime.utcnow()
        data = resp.json()
        assert data["year"] == now.year
        assert data["month"] == now.month

    def test_month_boundary(self, client, db_session):
        """月边界：7月31日的交易属于7月，8月1日属于8月"""
        add_tx(db_session, 1000, "餐饮", "expense", 31, month=7)
        add_tx(db_session, 2000, "餐饮", "expense", 1, month=8)
        db_session.commit()

        resp_july = client.get("/reports/monthly-summary?year=2026&month=7")
        assert resp_july.json()["total_expense"] == 1000

        resp_aug = client.get("/reports/monthly-summary?year=2026&month=8")
        assert resp_aug.json()["total_expense"] == 2000

    def test_year_transition(self, client, db_session):
        """跨年：12月和1月"""
        add_tx(db_session, 500, "餐饮", "expense", 31, month=12, year=2025)
        add_tx(db_session, 1000, "餐饮", "expense", 1, month=1, year=2026)
        db_session.commit()

        resp_dec = client.get("/reports/monthly-summary?year=2025&month=12")
        assert resp_dec.json()["total_expense"] == 500

        resp_jan = client.get("/reports/monthly-summary?year=2026&month=1")
        assert resp_jan.json()["total_expense"] == 1000

    def test_no_budgets(self, client, db_session):
        """没有预算时 budget_execution 为空列表"""
        add_tx(db_session, 1000, "餐饮", "expense", 10)
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        assert data["budget_execution"] == []

    def test_expense_percentage_calculation(self, client, db_session):
        """支出百分比计算正确"""
        add_tx(db_session, 750, "房租", "expense", 6)
        add_tx(db_session, 250, "餐饮", "expense", 10)
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        expenses = data["top_expenses"]
        assert expenses[0]["percentage"] == 75.0  # 750/1000
        assert expenses[1]["percentage"] == 25.0  # 250/1000

    def test_income_only_no_expense(self, client, db_session):
        """只有收入没有支出"""
        add_tx(db_session, 10000, "工资", "income", 5)
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        assert data["total_income"] == 10000
        assert data["total_expense"] == 0
        assert data["net_balance"] == 10000
        assert data["savings_rate"] == 100.0
        assert data["top_expenses"] == []
        assert len(data["top_incomes"]) == 1

    def test_expense_only_no_income(self, client, db_session):
        """只有支出没有收入"""
        add_tx(db_session, 1000, "餐饮", "expense", 10)
        db_session.commit()

        resp = client.get("/reports/monthly-summary?year=2026&month=7")
        data = resp.json()
        assert data["total_income"] == 0
        assert data["total_expense"] == 1000
        assert data["net_balance"] == -1000
        assert data["savings_rate"] == 0  # 无收入时储蓄率为0
        assert data["top_incomes"] == []
        assert len(data["top_expenses"]) == 1
