"""联动回归：dashboard 含账户余额、目标关联自动进度、交易回执 balance_updated。"""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_linkage_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

import app.main as main_mod
from app.main import app
from app.database import Base, get_db

main_mod.RATE_LIMIT_ENABLED = False

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture()
def auth():
    Base.metadata.create_all(bind=engine)
    prev_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    r = client.post(
        "/auth/register",
        json={"email": "linkage@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    token = r.json()["access_token"]
    uid = r.json()["user"]["id"]
    yield {"Authorization": f"Bearer {token}", "uid": uid}
    Base.metadata.drop_all(bind=engine)
    if prev_override is not None:
        app.dependency_overrides[get_db] = prev_override
    else:
        app.dependency_overrides.pop(get_db, None)


def _h(auth):
    return {"Authorization": auth["Authorization"]}


def test_dashboard_includes_account_balance(auth):
    # 建账户（开户余额 1000）+ 资产 5000 - 负债 2000，记一笔支出 100
    r = client.post("/accounts", headers=_h(auth), json={
        "name": "现金钱包", "account_type": "cash", "purpose": "consumption",
        "balance": 1000,
    })
    assert r.status_code in (200, 201), r.text
    r = client.post("/assets", headers=_h(auth), json={
        "name": "存款", "asset_type": "savings", "current_value": 5000,
        "initial_value": 5000,
    })
    assert r.status_code in (200, 201), r.text
    r = client.post("/liabilities", headers=_h(auth), json={
        "name": "花呗", "liability_type": "huabei", "total_amount": 2000,
        "current_amount": 2000,
    })
    assert r.status_code in (200, 201), r.text
    # 记支出 100（账户名对得上 → 余额联动）
    r = client.post("/transactions", headers=_h(auth), json={
        "amount": 100, "category": "餐饮", "account": "现金钱包",
        "transaction_type": "expense",
    })
    assert r.status_code in (200, 201), r.text
    assert r.json()["balance_updated"] is True
    # 净资产 = 900 + 5000 - 2000 = 3900（记账前会是 4000）
    r = client.get("/stats/dashboard", headers=_h(auth))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_account_balance"] == 900, d
    assert d["net_assets"] == 3900, d


def test_transaction_unmatched_account_warns(auth):
    r = client.post("/transactions", headers=_h(auth), json={
        "amount": 50, "category": "餐饮", "account": "不存在的账户",
        "transaction_type": "expense",
    })
    assert r.status_code in (200, 201), r.text
    assert r.json()["balance_updated"] is False


def test_goal_linked_account_auto_progress(auth):
    r = client.post("/accounts", headers=_h(auth), json={
        "name": "存钱罐", "account_type": "bank", "purpose": "goal",
        "balance": 3000,
    })
    assert r.status_code in (200, 201), r.text
    r = client.post("/goals", headers=_h(auth), json={
        "name": "旅行基金", "goal_type": "savings", "target_amount": 10000,
        "linked_account": "存钱罐",
    })
    assert r.status_code in (200, 201), r.text
    g = r.json()
    assert g["auto_progress"] is True
    assert g["current_amount"] == 3000
    assert g["progress_percent"] == 30.0
    # 关联目标拒绝手动投入
    r = client.post(f"/goals/{g['id']}/contribute", headers=_h(auth), json={
        "amount": 100,
    })
    assert r.status_code == 400, r.text


def test_goal_linked_asset_auto_progress(auth):
    r = client.post("/assets", headers=_h(auth), json={
        "name": "金条", "asset_type": "gold", "current_value": 5000,
        "initial_value": 4000,
    })
    assert r.status_code in (200, 201), r.text
    asset_id = r.json()["id"]
    r = client.post("/goals", headers=_h(auth), json={
        "name": "买金目标", "goal_type": "purchase", "target_amount": 20000,
        "linked_asset_id": asset_id,
    })
    assert r.status_code in (200, 201), r.text
    assert r.json()["current_amount"] == 5000


def test_internal_transfer_excluded_from_monthly_stats(auth):
    # 自建：账户 2000 + 资产 5000 - 负债 2000；支出 100（餐饮）+ 划转 500
    client.post("/accounts", headers=_h(auth), json={
        "name": "现金钱包", "account_type": "cash", "purpose": "consumption",
        "balance": 2000,
    })
    client.post("/assets", headers=_h(auth), json={
        "name": "存款", "asset_type": "savings", "current_value": 5000,
        "initial_value": 5000,
    })
    client.post("/liabilities", headers=_h(auth), json={
        "name": "花呗", "liability_type": "huabei", "total_amount": 2000,
        "current_amount": 2000,
    })
    client.post("/transactions", headers=_h(auth), json={
        "amount": 100, "category": "餐饮", "account": "现金钱包",
        "transaction_type": "expense",
    })
    r = client.post("/transactions", headers=_h(auth), json={
        "amount": 500, "category": "自账户划转", "account": "现金钱包",
        "transaction_type": "expense",
    })
    assert r.status_code in (200, 201), r.text
    assert r.json()["balance_updated"] is True
    r = client.get("/stats/dashboard", headers=_h(auth))
    d = r.json()
    # 本月支出只含餐饮 100，不含划转 500
    assert d["monthly_expenses"] == 100, d
    # 但余额扣了 500：1900 - 500 = 1400；净资产 = 1400 + 5000 - 2000 = 4400
    assert d["total_account_balance"] == 1400, d
    assert d["net_assets"] == 4400, d


def test_position_creates_typed_asset(auth):
    # 银行理财持仓双写资产类型应为 wealth_mgmt（不是 other）；黄金亦然
    for name, ptype in (("某理财", "wealth_mgmt"), ("金条ETF", "gold")):
        r = client.post("/positions", headers=_h(auth), json={
            "name": name, "symbol": "X", "position_type": ptype,
            "quantity": 10, "avg_cost": 100, "current_price": 110,
            "account": "证券",
        })
        assert r.status_code in (200, 201), r.text
    r = client.get("/assets", headers=_h(auth))
    by_name = {a["name"]: a["asset_type"] for a in r.json()}
    assert by_name.get("[持仓] 某理财") == "wealth_mgmt", by_name
    assert by_name.get("[持仓] 金条ETF") == "gold", by_name
