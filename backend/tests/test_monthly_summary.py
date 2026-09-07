"""V2-013 月度财务摘要测试"""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_monthly_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

import pytest
import json
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_mod
from app.main import app
from app.database import Base, get_db, Transaction, Account, Asset, Liability, Setting

main_mod.RATE_LIMIT_ENABLED = False

SQLALCHEMY_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(scope="function")
def auth():
    Base.metadata.create_all(bind=engine)
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    r = client.post(
        "/auth/register",
        json={"email": "monthly@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    j = r.json()
    token = j["access_token"]
    uid = j["user"]["id"]
    yield {"headers": {"Authorization": f"Bearer {token}"}, "user_id": uid}
    Base.metadata.drop_all(bind=engine)
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def _db():
    return TestingSessionLocal()


def add_tx(uid, amount, category, tx_type, day, month=7, year=2026):
    """快捷添加交易"""
    db = _db()
    try:
        db.add(Transaction(
            amount=amount,
            category=category,
            account="测试账户",
            transaction_type=tx_type,
            parsed_at=datetime(year, month, day, 12, 0),
            confidence=1.0,
            user_id=uid,
        ))
        db.commit()
    finally:
        db.close()


def add_rows(uid, *objs):
    db = _db()
    try:
        for o in objs:
            if hasattr(o, "user_id") and getattr(o, "user_id", None) is None:
                o.user_id = uid
            db.add(o)
        db.commit()
    finally:
        db.close()


class TestMonthlySummary:

    def test_empty_month(self, auth):
        """空月份：所有指标应为 0"""
        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
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

    def test_basic_income_expense(self, auth):
        """基本收支：收入10000，支出6000"""
        uid = auth["user_id"]
        add_tx(uid, 10000, "工资", "income", 5)
        add_tx(uid, 3000, "房租", "expense", 6)
        add_tx(uid, 2000, "餐饮", "expense", 10)
        add_tx(uid, 1000, "交通", "expense", 15)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total_income"] == 10000
        assert data["total_expense"] == 6000
        assert data["net_balance"] == 4000
        assert data["savings_rate"] == 40.0
        assert data["transaction_count"] == 4

    def test_savings_rate_zero_income(self, auth):
        """零收入时储蓄率应为0"""
        add_tx(auth["user_id"], 500, "餐饮", "expense", 1)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["savings_rate"] == 0

    def test_net_worth_calculation(self, auth):
        """净资产 = 账户余额 + 资产 - 负债"""
        uid = auth["user_id"]
        add_rows(uid,
                 Account(name="招行", account_type="bank", purpose="consumption", balance=5000),
                 Account(name="余额宝", account_type="alipay", purpose="emergency", balance=10000),
                 Asset(name="基金", asset_type="fund", current_value=20000),
                 Liability(name="花呗", liability_type="huabei", current_amount=3000, monthly_payment=500))

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["current_net_worth"] == 32000

    def test_net_worth_change_equals_net_balance(self, auth):
        """净资产变化 = 本月净收支"""
        uid = auth["user_id"]
        add_tx(uid, 8000, "工资", "income", 5)
        add_tx(uid, 3000, "房租", "expense", 6)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["net_worth_change"] == 5000

    def test_account_summary(self, auth):
        """四账户体系概览"""
        uid = auth["user_id"]
        add_rows(uid,
                 Account(name="招行", account_type="bank", purpose="consumption", balance=3000),
                 Account(name="微信", account_type="wechat", purpose="consumption", balance=2000),
                 Account(name="余额宝", account_type="alipay", purpose="emergency", balance=15000),
                 Account(name="基金账户", account_type="fund", purpose="investment", balance=8000),
                 Account(name="定期", account_type="bank", purpose="goal", balance=5000))

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        summary = data["account_summary"]
        assert summary["total_balance"] == 33000
        assert summary["by_purpose"]["consumption"]["count"] == 2
        assert summary["by_purpose"]["consumption"]["total_balance"] == 5000
        assert summary["by_purpose"]["emergency"]["total_balance"] == 15000
        assert summary["by_purpose"]["investment"]["total_balance"] == 8000
        assert summary["by_purpose"]["goal"]["total_balance"] == 5000

    def test_budget_execution(self, auth):
        """预算执行情况"""
        uid = auth["user_id"]
        budgets = [
            {"category": "房租", "monthly_limit": 3000, "level": "L1", "alert_threshold": 0.9},
            {"category": "餐饮", "monthly_limit": 2000, "level": "L1", "alert_threshold": 0.9},
            {"category": "娱乐", "monthly_limit": 500, "level": "L3", "alert_threshold": 0.8},
        ]
        add_rows(uid, Setting(key="budgets", value=json.dumps(budgets)))
        add_tx(uid, 3000, "房租", "expense", 6)
        add_tx(uid, 1500, "餐饮", "expense", 10)
        add_tx(uid, 600, "娱乐", "expense", 15)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
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

    def test_liability_summary(self, auth):
        """负债概览"""
        uid = auth["user_id"]
        add_rows(uid,
                 Liability(name="房贷", liability_type="mortgage", current_amount=500000, monthly_payment=3000),
                 Liability(name="花呗", liability_type="huabei", current_amount=2000, monthly_payment=500),
                 Liability(name="信用卡", liability_type="credit_card", current_amount=5000, monthly_payment=1000, status="active"))

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        liab = data["liability_summary"]
        assert liab["count"] == 3
        assert liab["total_debt"] == 507000
        assert liab["monthly_payment"] == 4500

    def test_top_expenses(self, auth):
        """支出分类排序"""
        uid = auth["user_id"]
        add_tx(uid, 3000, "房租", "expense", 6)
        add_tx(uid, 2000, "餐饮", "expense", 10)
        add_tx(uid, 1000, "交通", "expense", 15)
        add_tx(uid, 500, "娱乐", "expense", 20)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        expenses = data["top_expenses"]
        assert len(expenses) == 4
        assert expenses[0]["category"] == "房租"
        assert expenses[0]["amount"] == 3000
        assert expenses[0]["percentage"] == 46.2

    def test_top_incomes(self, auth):
        """收入分类排序"""
        uid = auth["user_id"]
        add_tx(uid, 10000, "工资", "income", 5)
        add_tx(uid, 2000, "兼职", "income", 10)
        add_tx(uid, 500, "理财收益", "income", 15)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        incomes = data["top_incomes"]
        assert len(incomes) == 3
        assert incomes[0]["category"] == "工资"
        assert incomes[0]["amount"] == 10000

    def test_period_string(self, auth):
        """period 字段格式"""
        resp = client.get("/reports/monthly-summary?year=2026&month=3", headers=auth["headers"])
        data = resp.json()
        assert data["period"] == "2026年3月"

    def test_default_month(self, auth):
        """不传年月时默认当前月"""
        resp = client.get("/reports/monthly-summary", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        now = datetime.utcnow()
        data = resp.json()
        assert data["year"] == now.year
        assert data["month"] == now.month

    def test_month_boundary(self, auth):
        """月边界：7月31日的交易属于7月，8月1日属于8月"""
        uid = auth["user_id"]
        add_tx(uid, 1000, "餐饮", "expense", 31, month=7)
        add_tx(uid, 2000, "餐饮", "expense", 1, month=8)

        resp_july = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        assert resp_july.json()["total_expense"] == 1000

        resp_aug = client.get("/reports/monthly-summary?year=2026&month=8", headers=auth["headers"])
        assert resp_aug.json()["total_expense"] == 2000

    def test_year_transition(self, auth):
        """跨年：12月和1月"""
        uid = auth["user_id"]
        add_tx(uid, 500, "餐饮", "expense", 31, month=12, year=2025)
        add_tx(uid, 1000, "餐饮", "expense", 1, month=1, year=2026)

        resp_dec = client.get("/reports/monthly-summary?year=2025&month=12", headers=auth["headers"])
        assert resp_dec.json()["total_expense"] == 500

        resp_jan = client.get("/reports/monthly-summary?year=2026&month=1", headers=auth["headers"])
        assert resp_jan.json()["total_expense"] == 1000

    def test_no_budgets(self, auth):
        """没有预算时 budget_execution 为空列表"""
        add_tx(auth["user_id"], 1000, "餐饮", "expense", 10)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["budget_execution"] == []

    def test_expense_percentage_calculation(self, auth):
        """支出百分比计算正确"""
        uid = auth["user_id"]
        add_tx(uid, 750, "房租", "expense", 6)
        add_tx(uid, 250, "餐饮", "expense", 10)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        expenses = data["top_expenses"]
        assert expenses[0]["percentage"] == 75.0
        assert expenses[1]["percentage"] == 25.0

    def test_income_only_no_expense(self, auth):
        """只有收入没有支出"""
        add_tx(auth["user_id"], 10000, "工资", "income", 5)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["total_income"] == 10000
        assert data["total_expense"] == 0
        assert data["net_balance"] == 10000
        assert data["savings_rate"] == 100.0
        assert data["top_expenses"] == []
        assert len(data["top_incomes"]) == 1

    def test_expense_only_no_income(self, auth):
        """只有支出没有收入"""
        add_tx(auth["user_id"], 1000, "餐饮", "expense", 10)

        resp = client.get("/reports/monthly-summary?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["total_income"] == 0
        assert data["total_expense"] == 1000
        assert data["net_balance"] == -1000
        assert data["savings_rate"] == 0
        assert data["top_incomes"] == []
        assert len(data["top_expenses"]) == 1
