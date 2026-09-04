"""账本守恒测试：导入联动余额、清空回滚余额、转账流水防直接改删."""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_ledger_test.db"
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
        json={"email": "ledger@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    token = r.json()["access_token"]
    yield {"Authorization": f"Bearer {token}"}
    Base.metadata.drop_all(bind=engine)
    if prev_override is not None:
        app.dependency_overrides[get_db] = prev_override
    else:
        app.dependency_overrides.pop(get_db, None)


def make_account(auth, name, balance):
    r = client.post(
        "/accounts",
        json={
            "name": name,
            "account_type": "bank",
            "purpose": "consumption",
            "balance": balance,
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    return r.json()


def get_balance(auth, acc_id):
    r = client.get(f"/accounts/{acc_id}", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["balance"]


def test_import_csv_links_balance(auth):
    acc = make_account(auth, "导入户", 1000.0)
    csv_text = (
        "日期,类型,金额,分类,账户,描述,置信度\n"
        "2026-09-04 10:00,expense,100.0,餐饮,导入户,测试,1.0\n"
    )
    r = client.post("/import/csv", json={"content": csv_text}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1
    assert get_balance(auth, acc["id"]) == 900.0


def test_delete_all_rolls_back_balances(auth):
    acc = make_account(auth, "清空户", 1000.0)
    r = client.post(
        "/transactions",
        json={
            "amount": 200.0,
            "category": "餐饮",
            "account": "清空户",
            "transaction_type": "expense",
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert get_balance(auth, acc["id"]) == 800.0
    r = client.delete("/transactions?confirm=true", headers=auth)
    assert r.status_code == 200, r.text
    assert get_balance(auth, acc["id"]) == 1000.0


def test_transfer_rows_reject_direct_edit_and_delete(auth):
    a = make_account(auth, "转出户", 1000.0)
    b = make_account(auth, "转入户", 0.0)
    r = client.post(
        "/accounts/transfer",
        json={"from_account_id": a["id"], "to_account_id": b["id"], "amount": 300.0},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert get_balance(auth, a["id"]) == 700.0
    assert get_balance(auth, b["id"]) == 300.0

    txs = client.get("/transactions?limit=10", headers=auth).json()
    out_tx = next(t for t in txs if t["category"] == "转账" and t["transaction_type"] == "expense")

    r = client.put(f"/transactions/{out_tx['id']}", json={"amount": 1.0}, headers=auth)
    assert r.status_code == 400, r.text
    r = client.delete(f"/transactions/{out_tx['id']}", headers=auth)
    assert r.status_code == 400, r.text
    # 余额未被破坏
    assert get_balance(auth, a["id"]) == 700.0
    assert get_balance(auth, b["id"]) == 300.0


def test_manual_create_normalizes_account_to_chinese(auth):
    r = client.post(
        "/transactions",
        json={
            "amount": 50.0,
            "category": "餐饮",
            "account": "cmb",
            "transaction_type": "expense",
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["account"] == "招商银行"


def test_list_filter_accepts_platform_id_and_chinese(auth):
    client.post(
        "/transactions",
        json={
            "amount": 50.0,
            "category": "餐饮",
            "account": "cmb",
            "transaction_type": "expense",
        },
        headers=auth,
    )
    for q in ("cmb", "招商银行"):
        r = client.get(f"/transactions?account={q}", headers=auth)
        assert r.status_code == 200, r.text
        assert len(r.json()) == 1, q
