"""V2-014 现金流报表测试"""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_cashflow_report_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

import pytest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_mod
from app.main import app
from app.database import Base, get_db, Transaction

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
        json={"email": "cashflowreport@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    j = r.json()
    yield {"headers": {"Authorization": f"Bearer {j['access_token']}"}, "user_id": j["user"]["id"]}
    Base.metadata.drop_all(bind=engine)
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def add_tx(uid, amount, category, tx_type, day, month=7, year=2026, account="招行"):
    db = TestingSessionLocal()
    try:
        db.add(Transaction(
            amount=amount,
            category=category,
            account=account,
            transaction_type=tx_type,
            parsed_at=datetime(year, month, day, 12, 0),
            confidence=1.0,
            user_id=uid,
        ))
        db.commit()
    finally:
        db.close()


class TestCashflowReport:

    def test_empty_month(self, auth):
        """空月份：所有指标为0"""
        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total_inflow"] == 0
        assert data["total_outflow"] == 0
        assert data["net_cashflow"] == 0
        assert data["transaction_count"] == 0
        assert data["active_days"] == 0
        assert len(data["daily"]) == 31
        assert data["account_breakdown"] == []

    def test_basic_inflow_outflow(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 10000, "工资", "income", 5)
        add_tx(uid, 3000, "房租", "expense", 6)
        add_tx(uid, 2000, "餐饮", "expense", 10)

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["total_inflow"] == 10000
        assert data["total_outflow"] == 5000
        assert data["net_cashflow"] == 5000
        assert data["transaction_count"] == 3
        assert data["active_days"] == 3

    def test_daily_breakdown(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 1000, "工资", "income", 5)
        add_tx(uid, 500, "餐饮", "expense", 5)
        add_tx(uid, 200, "交通", "expense", 10)

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        daily = data["daily"]

        day5 = next(d for d in daily if d["day"] == 5)
        assert day5["inflow"] == 1000
        assert day5["outflow"] == 500
        assert day5["net"] == 500
        assert day5["transaction_count"] == 2

        day10 = next(d for d in daily if d["day"] == 10)
        assert day10["inflow"] == 0
        assert day10["outflow"] == 200
        assert day10["net"] == -200

        day1 = next(d for d in daily if d["day"] == 1)
        assert day1["inflow"] == 0
        assert day1["outflow"] == 0
        assert day1["transaction_count"] == 0

    def test_days_in_month_count(self, auth):
        jul = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"]).json()
        assert len(jul["daily"]) == 31

        feb = client.get("/reports/cashflow?year=2026&month=2", headers=auth["headers"]).json()
        assert len(feb["daily"]) == 28

        feb_leap = client.get("/reports/cashflow?year=2024&month=2", headers=auth["headers"]).json()
        assert len(feb_leap["daily"]) == 29

    def test_comparison_with_prev_month(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 8000, "工资", "income", 5, month=6)
        add_tx(uid, 4000, "房租", "expense", 6, month=6)
        add_tx(uid, 10000, "工资", "income", 5)
        add_tx(uid, 3000, "房租", "expense", 6)

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        comp = data["comparison"]
        assert comp["prev_period"] == "2026年6月"
        assert comp["prev_inflow"] == 8000
        assert comp["prev_outflow"] == 4000
        assert comp["inflow_change"] == 2000
        assert comp["outflow_change"] == -1000
        assert comp["net_change"] == 3000
        assert comp["inflow_change_pct"] == 25.0

    def test_comparison_prev_month_empty(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 1000, "工资", "income", 5)

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        comp = data["comparison"]
        assert comp["prev_inflow"] == 0
        assert comp["prev_outflow"] == 0
        assert comp["inflow_change_pct"] == 0

    def test_account_breakdown(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 5000, "工资", "income", 5, account="招行")
        add_tx(uid, 2000, "餐饮", "expense", 6, account="微信")
        add_tx(uid, 1000, "购物", "expense", 10, account="招行")

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        breakdown = data["account_breakdown"]
        assert len(breakdown) == 2

        zh = next(b for b in breakdown if b["account"] == "招行")
        assert zh["inflow"] == 5000
        assert zh["outflow"] == 1000
        assert zh["net"] == 4000

        wx = next(b for b in breakdown if b["account"] == "微信")
        assert wx["inflow"] == 0
        assert wx["outflow"] == 2000
        assert wx["net"] == -2000

    def test_ytd(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 10000, "工资", "income", 5, month=1)
        add_tx(uid, 3000, "房租", "expense", 6, month=1)
        add_tx(uid, 10000, "工资", "income", 5, month=7)
        add_tx(uid, 2000, "餐饮", "expense", 10, month=7)

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        ytd = data["ytd"]
        assert ytd["inflow"] == 20000
        assert ytd["outflow"] == 5000
        assert ytd["net"] == 15000

    def test_account_filter(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 5000, "工资", "income", 5, account="招行")
        add_tx(uid, 2000, "餐饮", "expense", 6, account="微信")

        resp = client.get("/reports/cashflow?year=2026&month=7&account=招行", headers=auth["headers"])
        data = resp.json()
        assert data["total_inflow"] == 5000
        assert data["total_outflow"] == 0
        assert data["account"] == "招行"

    def test_default_month(self, auth):
        resp = client.get("/reports/cashflow", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        now = datetime.utcnow()
        data = resp.json()
        assert data["year"] == now.year
        assert data["month"] == now.month

    def test_period_string(self, auth):
        data = client.get("/reports/cashflow?year=2026&month=3", headers=auth["headers"]).json()
        assert data["period"] == "2026年3月"

    def test_month_boundary(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 500, "餐饮", "expense", 30, month=6)
        add_tx(uid, 1000, "工资", "income", 1, month=7)

        jun = client.get("/reports/cashflow?year=2026&month=6", headers=auth["headers"]).json()
        assert jun["total_outflow"] == 500
        assert jun["total_inflow"] == 0

        jul = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"]).json()
        assert jul["total_inflow"] == 1000
        assert jul["total_outflow"] == 0

    def test_year_transition_comparison(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 5000, "工资", "income", 15, month=12, year=2025)
        add_tx(uid, 10000, "工资", "income", 15, month=1, year=2026)

        resp = client.get("/reports/cashflow?year=2026&month=1", headers=auth["headers"])
        data = resp.json()
        comp = data["comparison"]
        assert comp["prev_period"] == "2025年12月"
        assert comp["prev_inflow"] == 5000
        assert comp["inflow_change"] == 5000

    def test_avg_daily(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 3100, "工资", "income", 1)

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["avg_daily_inflow"] == 100.0
        assert data["avg_daily_outflow"] == 0.0

    def test_income_only(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 10000, "工资", "income", 5)

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["total_inflow"] == 10000
        assert data["total_outflow"] == 0
        assert data["net_cashflow"] == 10000
        assert len(data["account_breakdown"]) == 1

    def test_expense_only(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 2000, "房租", "expense", 6)

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["total_inflow"] == 0
        assert data["total_outflow"] == 2000
        assert data["net_cashflow"] == -2000

    def test_outflow_change_pct_zero_prev(self, auth):
        uid = auth["user_id"]
        add_tx(uid, 1000, "餐饮", "expense", 5)

        resp = client.get("/reports/cashflow?year=2026&month=7", headers=auth["headers"])
        data = resp.json()
        assert data["comparison"]["outflow_change_pct"] == 0
