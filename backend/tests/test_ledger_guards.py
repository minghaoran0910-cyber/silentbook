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


def test_login_cookie_secure_follows_env(auth):
    import app.auth as auth_mod

    r = client.post(
        "/auth/login",
        json={"account": "ledger@test.local", "password": "Testpass123"},
    )
    assert r.status_code == 200, r.text
    set_cookie = r.headers.get("set-cookie", "")
    assert "auth_token=" in set_cookie
    assert "Secure" not in set_cookie  # 测试环境默认不 Secure，http 可用

    auth_mod.COOKIE_SECURE = True
    try:
        r = client.post(
            "/auth/login",
            json={"account": "ledger@test.local", "password": "Testpass123"},
        )
        assert "Secure" in r.headers.get("set-cookie", "")
    finally:
        auth_mod.COOKIE_SECURE = False


def _minimal_pdf_bytes(lines):
    """手写最小 PDF（Helvetica 内建字体，无需外部字体文件）供 pdfplumber 提取。"""
    content = "BT /F1 11 Tf 50 800 Td 14 TL\n"
    parts = []
    for i, line in enumerate(lines):
        esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        parts.append(f"({esc}) Tj")
        if i < len(lines) - 1:
            parts.append("T*")
    content += " ".join(parts) + " ET\n"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content.encode())} >>\nstream\n{content}endstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offsets:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_import_pdf_wires_parser_and_links_balance(auth):
    pdf = _minimal_pdf_bytes([
        "2024/01/15 Starbucks 31.90 6025.93",
        "2024/01/16 Didi 25.80 6000.13",
    ])
    r = client.post(
        "/import/pdf",
        files={"file": ("stmt.pdf", pdf, "application/pdf")},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "ok", d
    assert d["imported"] == 2, d


def test_update_rejects_bad_type(auth):
    r = client.post(
        "/transactions",
        json={"amount": 10.0, "category": "餐饮", "account": "现金",
              "transaction_type": "expense"},
        headers=auth,
    )
    tx_id = r.json()["id"]
    r = client.put(f"/transactions/{tx_id}",
                   json={"transaction_type": "transfer"}, headers=auth)
    assert r.status_code == 422, r.text


def test_import_csv_skips_unknown_type(auth):
    csv_text = (
        "日期,类型,金额,分类,账户,描述,置信度\n"
        "2026-09-04 10:00,transfer,100.0,储蓄,现金,自动攒,1.0\n"
        "2026-09-04 10:01,expense,50.0,餐饮,现金,午饭,1.0\n"
    )
    r = client.post("/import/csv", json={"content": csv_text}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": 1, "skipped": 1}
