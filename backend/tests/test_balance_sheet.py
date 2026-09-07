"""V2-015 资产负债表测试"""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_balance_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_mod
from app.main import app
from app.database import Base, get_db, Asset, Liability, Account

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
        json={"email": "balance@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    j = r.json()
    yield {"headers": {"Authorization": f"Bearer {j['access_token']}"}, "user_id": j["user"]["id"]}
    Base.metadata.drop_all(bind=engine)
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def add_asset(uid, name, asset_type, current_value, initial_value=None, status="active"):
    db = TestingSessionLocal()
    try:
        db.add(Asset(
            name=name, asset_type=asset_type, current_value=current_value,
            initial_value=initial_value if initial_value is not None else current_value,
            status=status, user_id=uid,
        ))
        db.commit()
    finally:
        db.close()


def add_liability(uid, name, liability_type, current_amount, total_amount=None, monthly_payment=0, status="active"):
    db = TestingSessionLocal()
    try:
        db.add(Liability(
            name=name, liability_type=liability_type,
            current_amount=current_amount,
            total_amount=total_amount if total_amount is not None else current_amount,
            monthly_payment=monthly_payment,
            status=status, user_id=uid,
        ))
        db.commit()
    finally:
        db.close()


def add_account(uid, name, account_type, purpose, balance):
    db = TestingSessionLocal()
    try:
        db.add(Account(name=name, account_type=account_type, purpose=purpose, balance=balance, user_id=uid))
        db.commit()
    finally:
        db.close()


class TestBalanceSheet:

    def test_empty(self, auth):
        resp = client.get("/reports/balance-sheet", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total_assets"] == 0
        assert data["total_liabilities"] == 0
        assert data["net_worth"] == 0
        assert data["debt_ratio"] == 0
        assert data["health_status"] == "empty"
        assert data["asset_count"] == 0
        assert data["liability_count"] == 0

    def test_assets_only(self, auth):
        uid = auth["user_id"]
        add_asset(uid, "现金", "cash", 10000)
        add_asset(uid, "基金A", "fund", 20000, initial_value=15000)

        resp = client.get("/reports/balance-sheet", headers=auth["headers"])
        data = resp.json()
        assert data["total_assets"] == 30000
        assert data["total_liabilities"] == 0
        assert data["net_worth"] == 30000
        assert data["debt_ratio"] == 0
        assert data["health_status"] == "healthy"

    def test_liabilities_only(self, auth):
        add_liability(auth["user_id"], "花呗", "huabei", 2000, monthly_payment=500)

        resp = client.get("/reports/balance-sheet", headers=auth["headers"])
        data = resp.json()
        assert data["total_assets"] == 0
        assert data["total_liabilities"] == 2000
        assert data["net_worth"] == -2000
        assert data["debt_ratio"] == 0

    def test_both_assets_liabilities(self, auth):
        uid = auth["user_id"]
        add_asset(uid, "存款", "savings", 100000)
        add_asset(uid, "基金", "fund", 50000)
        add_liability(uid, "房贷", "mortgage", 300000, monthly_payment=3000)
        add_liability(uid, "花呗", "huabei", 2000, monthly_payment=500)

        resp = client.get("/reports/balance-sheet", headers=auth["headers"])
        data = resp.json()
        assert data["total_assets"] == 150000
        assert data["total_liabilities"] == 302000
        assert data["net_worth"] == -152000
        assert data["debt_ratio"] == 201.3

    def test_asset_breakdown_by_type(self, auth):
        uid = auth["user_id"]
        add_asset(uid, "现金1", "cash", 5000)
        add_asset(uid, "现金2", "cash", 3000)
        add_asset(uid, "基金A", "fund", 20000)
        add_asset(uid, "股票B", "stock", 10000)

        resp = client.get("/reports/balance-sheet", headers=auth["headers"])
        data = resp.json()
        by_type = data["assets_by_type"]
        assert "cash" in by_type
        assert by_type["cash"]["total_value"] == 8000
        assert by_type["cash"]["count"] == 2
        assert "fund" in by_type
        assert by_type["fund"]["total_value"] == 20000
        assert "stock" in by_type
        assert by_type["stock"]["total_value"] == 10000

    def test_liability_breakdown_by_type(self, auth):
        uid = auth["user_id"]
        add_liability(uid, "房贷", "mortgage", 500000)
        add_liability(uid, "车贷", "car_loan", 100000)
        add_liability(uid, "花呗", "huabei", 1000)
        add_liability(uid, "白条", "baitiao", 500)

        resp = client.get("/reports/balance-sheet", headers=auth["headers"])
        data = resp.json()
        by_type = data["liabilities_by_type"]
        assert "mortgage" in by_type
        assert by_type["mortgage"]["total_amount"] == 500000
        assert "car_loan" in by_type
        assert by_type["car_loan"]["total_amount"] == 100000
        assert "huabei" in by_type
        assert "baitiao" in by_type

    def test_debt_ratio_healthy(self, auth):
        uid = auth["user_id"]
        add_asset(uid, "存款", "savings", 100000)
        add_liability(uid, "花呗", "huabei", 20000)

        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert data["debt_ratio"] == 20.0
        assert data["health_status"] == "healthy"

    def test_debt_ratio_normal(self, auth):
        uid = auth["user_id"]
        add_asset(uid, "存款", "savings", 100000)
        add_liability(uid, "房贷", "mortgage", 40000)

        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert data["debt_ratio"] == 40.0
        assert data["health_status"] == "normal"

    def test_debt_ratio_warning(self, auth):
        uid = auth["user_id"]
        add_asset(uid, "存款", "savings", 100000)
        add_liability(uid, "房贷", "mortgage", 60000)

        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert data["debt_ratio"] == 60.0
        assert data["health_status"] == "warning"

    def test_debt_ratio_danger(self, auth):
        uid = auth["user_id"]
        add_asset(uid, "存款", "savings", 100000)
        add_liability(uid, "房贷", "mortgage", 80000)

        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert data["debt_ratio"] == 80.0
        assert data["health_status"] == "danger"

    def test_gain_loss_calculation(self, auth):
        uid = auth["user_id"]
        add_asset(uid, "基金A", "fund", 12000, initial_value=10000)
        add_asset(uid, "股票B", "stock", 8000, initial_value=10000)

        resp = client.get("/reports/balance-sheet", headers=auth["headers"])
        data = resp.json()
        fund_items = data["assets_by_type"]["fund"]["items"]
        stock_items = data["assets_by_type"]["stock"]["items"]
        assert fund_items[0]["gain_loss"] == 2000
        assert fund_items[0]["gain_loss_pct"] == 20.0
        assert stock_items[0]["gain_loss"] == -2000
        assert stock_items[0]["gain_loss_pct"] == -20.0

    def test_inactive_assets_excluded(self, auth):
        uid = auth["user_id"]
        add_asset(uid, "活跃资产", "cash", 10000, status="active")
        add_asset(uid, "冻结资产", "cash", 5000, status="frozen")

        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert data["total_assets"] == 10000
        assert data["asset_count"] == 1

    def test_paid_liabilities_excluded(self, auth):
        uid = auth["user_id"]
        add_liability(uid, "活跃负债", "huabei", 2000, status="active")
        add_liability(uid, "已还清", "loan", 0, status="paid")

        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert data["total_liabilities"] == 2000
        assert data["liability_count"] == 1

    def test_account_balance_included(self, auth):
        uid = auth["user_id"]
        add_account(uid, "招行", "bank", "consumption", 5000)
        add_account(uid, "余额宝", "alipay", "emergency", 15000)
        add_asset(uid, "基金", "fund", 20000)
        add_liability(uid, "花呗", "huabei", 3000)

        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert data["total_account_balance"] == 20000
        assert data["total_assets"] == 20000
        assert data["total_liabilities"] == 3000
        assert data["net_worth"] == 17000
        assert data["total_net_worth"] == 37000

    def test_as_of_timestamp(self, auth):
        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert "as_of" in data
        assert len(data["as_of"]) > 10

    def test_unknown_asset_type(self, auth):
        add_asset(auth["user_id"], "奇怪的资产", "crypto", 5000)

        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert "other" in data["assets_by_type"]
        assert data["assets_by_type"]["other"]["total_value"] == 5000

    def test_unknown_liability_type(self, auth):
        add_liability(auth["user_id"], "奇怪负债", "unknown_type", 1000)

        data = client.get("/reports/balance-sheet", headers=auth["headers"]).json()
        assert "other" in data["liabilities_by_type"]
        assert data["liabilities_by_type"]["other"]["total_amount"] == 1000
