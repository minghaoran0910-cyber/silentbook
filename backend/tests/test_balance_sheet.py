"""V2-015 资产负债表测试"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime

from app.database import Base, get_db, Asset, Liability, Account
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


def add_asset(db, name, asset_type, current_value, initial_value=None, status="active"):
    db.add(Asset(
        name=name, asset_type=asset_type, current_value=current_value,
        initial_value=initial_value if initial_value is not None else current_value,
        status=status,
    ))


def add_liability(db, name, liability_type, current_amount, total_amount=None, monthly_payment=0, status="active"):
    db.add(Liability(
        name=name, liability_type=liability_type,
        current_amount=current_amount,
        total_amount=total_amount if total_amount is not None else current_amount,
        monthly_payment=monthly_payment,
        status=status,
    ))


class TestBalanceSheet:

    def test_empty(self, client):
        """无资产无负债"""
        resp = client.get("/reports/balance-sheet")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_assets"] == 0
        assert data["total_liabilities"] == 0
        assert data["net_worth"] == 0
        assert data["debt_ratio"] == 0
        assert data["health_status"] == "empty"
        assert data["asset_count"] == 0
        assert data["liability_count"] == 0

    def test_assets_only(self, client, db_session):
        """只有资产无负债"""
        add_asset(db_session, "现金", "cash", 10000)
        add_asset(db_session, "基金A", "fund", 20000, initial_value=15000)
        db_session.commit()

        resp = client.get("/reports/balance-sheet")
        data = resp.json()
        assert data["total_assets"] == 30000
        assert data["total_liabilities"] == 0
        assert data["net_worth"] == 30000
        assert data["debt_ratio"] == 0
        assert data["health_status"] == "healthy"

    def test_liabilities_only(self, client, db_session):
        """只有负债无资产"""
        add_liability(db_session, "花呗", "huabei", 2000, monthly_payment=500)
        db_session.commit()

        resp = client.get("/reports/balance-sheet")
        data = resp.json()
        assert data["total_assets"] == 0
        assert data["total_liabilities"] == 2000
        assert data["net_worth"] == -2000
        assert data["debt_ratio"] == 0  # 无资产时比率为0

    def test_both_assets_liabilities(self, client, db_session):
        """资产和负债都有"""
        add_asset(db_session, "存款", "savings", 100000)
        add_asset(db_session, "基金", "fund", 50000)
        add_liability(db_session, "房贷", "mortgage", 300000, monthly_payment=3000)
        add_liability(db_session, "花呗", "huabei", 2000, monthly_payment=500)
        db_session.commit()

        resp = client.get("/reports/balance-sheet")
        data = resp.json()
        assert data["total_assets"] == 150000
        assert data["total_liabilities"] == 302000
        assert data["net_worth"] == -152000
        assert data["debt_ratio"] == 201.3  # 302000/150000*100

    def test_asset_breakdown_by_type(self, client, db_session):
        """资产按类型分组"""
        add_asset(db_session, "现金1", "cash", 5000)
        add_asset(db_session, "现金2", "cash", 3000)
        add_asset(db_session, "基金A", "fund", 20000)
        add_asset(db_session, "股票B", "stock", 10000)
        db_session.commit()

        resp = client.get("/reports/balance-sheet")
        data = resp.json()
        by_type = data["assets_by_type"]
        assert "cash" in by_type
        assert by_type["cash"]["total_value"] == 8000
        assert by_type["cash"]["count"] == 2
        assert "fund" in by_type
        assert by_type["fund"]["total_value"] == 20000
        assert "stock" in by_type
        assert by_type["stock"]["total_value"] == 10000

    def test_liability_breakdown_by_type(self, client, db_session):
        """负债按类型分组"""
        add_liability(db_session, "房贷", "mortgage", 500000)
        add_liability(db_session, "车贷", "car_loan", 100000)
        add_liability(db_session, "花呗", "huabei", 1000)
        add_liability(db_session, "白条", "baitiao", 500)
        db_session.commit()

        resp = client.get("/reports/balance-sheet")
        data = resp.json()
        by_type = data["liabilities_by_type"]
        assert "mortgage" in by_type
        assert by_type["mortgage"]["total_amount"] == 500000
        assert "car_loan" in by_type
        assert by_type["car_loan"]["total_amount"] == 100000
        assert "huabei" in by_type
        assert "baitiao" in by_type

    def test_debt_ratio_healthy(self, client, db_session):
        """资产负债率 < 30% = healthy"""
        add_asset(db_session, "存款", "savings", 100000)
        add_liability(db_session, "花呗", "huabei", 20000)
        db_session.commit()

        data = client.get("/reports/balance-sheet").json()
        assert data["debt_ratio"] == 20.0
        assert data["health_status"] == "healthy"

    def test_debt_ratio_normal(self, client, db_session):
        """30% <= 资产负债率 < 50% = normal"""
        add_asset(db_session, "存款", "savings", 100000)
        add_liability(db_session, "房贷", "mortgage", 40000)
        db_session.commit()

        data = client.get("/reports/balance-sheet").json()
        assert data["debt_ratio"] == 40.0
        assert data["health_status"] == "normal"

    def test_debt_ratio_warning(self, client, db_session):
        """50% <= 资产负债率 < 70% = warning"""
        add_asset(db_session, "存款", "savings", 100000)
        add_liability(db_session, "房贷", "mortgage", 60000)
        db_session.commit()

        data = client.get("/reports/balance-sheet").json()
        assert data["debt_ratio"] == 60.0
        assert data["health_status"] == "warning"

    def test_debt_ratio_danger(self, client, db_session):
        """资产负债率 >= 70% = danger"""
        add_asset(db_session, "存款", "savings", 100000)
        add_liability(db_session, "房贷", "mortgage", 80000)
        db_session.commit()

        data = client.get("/reports/balance-sheet").json()
        assert data["debt_ratio"] == 80.0
        assert data["health_status"] == "danger"

    def test_gain_loss_calculation(self, client, db_session):
        """资产盈亏计算"""
        add_asset(db_session, "基金A", "fund", 12000, initial_value=10000)
        add_asset(db_session, "股票B", "stock", 8000, initial_value=10000)
        db_session.commit()

        resp = client.get("/reports/balance-sheet")
        data = resp.json()
        fund_items = data["assets_by_type"]["fund"]["items"]
        stock_items = data["assets_by_type"]["stock"]["items"]
        assert fund_items[0]["gain_loss"] == 2000
        assert fund_items[0]["gain_loss_pct"] == 20.0
        assert stock_items[0]["gain_loss"] == -2000
        assert stock_items[0]["gain_loss_pct"] == -20.0

    def test_inactive_assets_excluded(self, client, db_session):
        """非active状态的资产不纳入"""
        add_asset(db_session, "活跃资产", "cash", 10000, status="active")
        add_asset(db_session, "冻结资产", "cash", 5000, status="frozen")
        db_session.commit()

        data = client.get("/reports/balance-sheet").json()
        assert data["total_assets"] == 10000
        assert data["asset_count"] == 1

    def test_paid_liabilities_excluded(self, client, db_session):
        """已还清的负债不纳入"""
        add_liability(db_session, "活跃负债", "huabei", 2000, status="active")
        add_liability(db_session, "已还清", "loan", 0, status="paid")
        db_session.commit()

        data = client.get("/reports/balance-sheet").json()
        assert data["total_liabilities"] == 2000
        assert data["liability_count"] == 1

    def test_account_balance_included(self, client, db_session):
        """账户余额纳入总净资产"""
        db_session.add(Account(name="招行", account_type="bank", purpose="consumption", balance=5000))
        db_session.add(Account(name="余额宝", account_type="alipay", purpose="emergency", balance=15000))
        add_asset(db_session, "基金", "fund", 20000)
        add_liability(db_session, "花呗", "huabei", 3000)
        db_session.commit()

        data = client.get("/reports/balance-sheet").json()
        assert data["total_account_balance"] == 20000
        assert data["total_assets"] == 20000
        assert data["total_liabilities"] == 3000
        assert data["net_worth"] == 17000  # 20000 - 3000
        assert data["total_net_worth"] == 37000  # 17000 + 20000(账户)

    def test_as_of_timestamp(self, client):
        """as_of 时间戳存在"""
        data = client.get("/reports/balance-sheet").json()
        assert "as_of" in data
        assert len(data["as_of"]) > 10

    def test_unknown_asset_type(self, client, db_session):
        """未知资产类型归入other"""
        add_asset(db_session, "奇怪的资产", "crypto", 5000)  # crypto不在标准类型中
        db_session.commit()

        data = client.get("/reports/balance-sheet").json()
        assert "other" in data["assets_by_type"]
        assert data["assets_by_type"]["other"]["total_value"] == 5000

    def test_unknown_liability_type(self, client, db_session):
        """未知负债类型归入other"""
        add_liability(db_session, "奇怪负债", "unknown_type", 1000)
        db_session.commit()

        data = client.get("/reports/balance-sheet").json()
        assert "other" in data["liabilities_by_type"]
        assert data["liabilities_by_type"]["other"]["total_amount"] == 1000
