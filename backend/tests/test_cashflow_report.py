"""V2-014 现金流报表测试"""
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


def add_tx(db, amount, category, tx_type, day, month=7, year=2026, account="招行"):
    db.add(Transaction(
        amount=amount,
        category=category,
        account=account,
        transaction_type=tx_type,
        parsed_at=datetime(year, month, day, 12, 0),
        confidence=1.0,
    ))


class TestCashflowReport:

    def test_empty_month(self, client):
        """空月份：所有指标为0"""
        resp = client.get("/reports/cashflow?year=2026&month=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_inflow"] == 0
        assert data["total_outflow"] == 0
        assert data["net_cashflow"] == 0
        assert data["transaction_count"] == 0
        assert data["active_days"] == 0
        assert len(data["daily"]) == 31  # 7月有31天
        assert data["account_breakdown"] == []

    def test_basic_inflow_outflow(self, client, db_session):
        """基本流入流出"""
        add_tx(db_session, 10000, "工资", "income", 5)
        add_tx(db_session, 3000, "房租", "expense", 6)
        add_tx(db_session, 2000, "餐饮", "expense", 10)
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
        data = resp.json()
        assert data["total_inflow"] == 10000
        assert data["total_outflow"] == 5000
        assert data["net_cashflow"] == 5000
        assert data["transaction_count"] == 3
        assert data["active_days"] == 3

    def test_daily_breakdown(self, client, db_session):
        """日明细：每天的收入/支出/净额"""
        add_tx(db_session, 1000, "工资", "income", 5)
        add_tx(db_session, 500, "餐饮", "expense", 5)
        add_tx(db_session, 200, "交通", "expense", 10)
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
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

    def test_days_in_month_count(self, client):
        """不同月份天数正确"""
        jul = client.get("/reports/cashflow?year=2026&month=7").json()
        assert len(jul["daily"]) == 31

        feb = client.get("/reports/cashflow?year=2026&month=2").json()
        assert len(feb["daily"]) == 28  # 2026年2月非闰月

        feb_leap = client.get("/reports/cashflow?year=2024&month=2").json()
        assert len(feb_leap["daily"]) == 29  # 2024是闰年

    def test_comparison_with_prev_month(self, client, db_session):
        """环比：与上月对比"""
        # 上月（6月）数据
        add_tx(db_session, 8000, "工资", "income", 5, month=6)
        add_tx(db_session, 4000, "房租", "expense", 6, month=6)
        # 本月（7月）数据
        add_tx(db_session, 10000, "工资", "income", 5)
        add_tx(db_session, 3000, "房租", "expense", 6)
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
        data = resp.json()
        comp = data["comparison"]
        assert comp["prev_period"] == "2026年6月"
        assert comp["prev_inflow"] == 8000
        assert comp["prev_outflow"] == 4000
        assert comp["inflow_change"] == 2000
        assert comp["outflow_change"] == -1000
        assert comp["net_change"] == 3000
        assert comp["inflow_change_pct"] == 25.0  # (10000-8000)/8000

    def test_comparison_prev_month_empty(self, client, db_session):
        """上月无数据时环比值都为0"""
        add_tx(db_session, 1000, "工资", "income", 5)
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
        data = resp.json()
        comp = data["comparison"]
        assert comp["prev_inflow"] == 0
        assert comp["prev_outflow"] == 0
        assert comp["inflow_change_pct"] == 0

    def test_account_breakdown(self, client, db_session):
        """按账户分解"""
        add_tx(db_session, 5000, "工资", "income", 5, account="招行")
        add_tx(db_session, 2000, "餐饮", "expense", 6, account="微信")
        add_tx(db_session, 1000, "购物", "expense", 10, account="招行")
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
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

    def test_ytd(self, client, db_session):
        """年初至今累计"""
        add_tx(db_session, 10000, "工资", "income", 5, month=1)
        add_tx(db_session, 3000, "房租", "expense", 6, month=1)
        add_tx(db_session, 10000, "工资", "income", 5, month=7)
        add_tx(db_session, 2000, "餐饮", "expense", 10, month=7)
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
        data = resp.json()
        ytd = data["ytd"]
        assert ytd["inflow"] == 20000
        assert ytd["outflow"] == 5000
        assert ytd["net"] == 15000

    def test_account_filter(self, client, db_session):
        """账户筛选"""
        add_tx(db_session, 5000, "工资", "income", 5, account="招行")
        add_tx(db_session, 2000, "餐饮", "expense", 6, account="微信")
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7&account=招行")
        data = resp.json()
        assert data["total_inflow"] == 5000
        assert data["total_outflow"] == 0
        assert data["account"] == "招行"

    def test_default_month(self, client):
        """默认当前月"""
        resp = client.get("/reports/cashflow")
        assert resp.status_code == 200
        now = datetime.utcnow()
        data = resp.json()
        assert data["year"] == now.year
        assert data["month"] == now.month

    def test_period_string(self, client):
        """period 字段"""
        data = client.get("/reports/cashflow?year=2026&month=3").json()
        assert data["period"] == "2026年3月"

    def test_month_boundary(self, client, db_session):
        """月边界：6月30日属于6月，7月1日属于7月"""
        add_tx(db_session, 500, "餐饮", "expense", 30, month=6)
        add_tx(db_session, 1000, "工资", "income", 1, month=7)
        db_session.commit()

        jun = client.get("/reports/cashflow?year=2026&month=6").json()
        assert jun["total_outflow"] == 500
        assert jun["total_inflow"] == 0

        jul = client.get("/reports/cashflow?year=2026&month=7").json()
        assert jul["total_inflow"] == 1000
        assert jul["total_outflow"] == 0

    def test_year_transition_comparison(self, client, db_session):
        """跨年环比：1月 vs 去年12月"""
        add_tx(db_session, 5000, "工资", "income", 15, month=12, year=2025)
        add_tx(db_session, 10000, "工资", "income", 15, month=1, year=2026)
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=1")
        data = resp.json()
        comp = data["comparison"]
        assert comp["prev_period"] == "2025年12月"
        assert comp["prev_inflow"] == 5000
        assert comp["inflow_change"] == 5000

    def test_avg_daily(self, client, db_session):
        """日均流入流出"""
        add_tx(db_session, 3100, "工资", "income", 1)  # 7月1日
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
        data = resp.json()
        assert data["avg_daily_inflow"] == 100.0  # 3100/31
        assert data["avg_daily_outflow"] == 0.0

    def test_income_only(self, client, db_session):
        """只有流入"""
        add_tx(db_session, 10000, "工资", "income", 5)
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
        data = resp.json()
        assert data["total_inflow"] == 10000
        assert data["total_outflow"] == 0
        assert data["net_cashflow"] == 10000
        assert len(data["account_breakdown"]) == 1

    def test_expense_only(self, client, db_session):
        """只有流出"""
        add_tx(db_session, 2000, "房租", "expense", 6)
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
        data = resp.json()
        assert data["total_inflow"] == 0
        assert data["total_outflow"] == 2000
        assert data["net_cashflow"] == -2000

    def test_outflow_change_pct_zero_prev(self, client, db_session):
        """上月支出为0时变化百分比为0"""
        add_tx(db_session, 1000, "餐饮", "expense", 5)
        db_session.commit()

        resp = client.get("/reports/cashflow?year=2026&month=7")
        data = resp.json()
        assert data["comparison"]["outflow_change_pct"] == 0
