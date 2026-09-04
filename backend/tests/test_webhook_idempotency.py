"""Webhook HMAC 校验 + 传输/业务两级幂等测试.

覆盖: 签名正确性、5 分钟窗口、event_id 重放(409)、
同一条通知换 event_id 重试不重记(duplicate)、batch 逐条去重、
解析器不可用时回 503(不再吞成 200)。
"""
import hashlib
import hmac
import json
import os
import time

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_wh_idem_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

import app.main as main_mod
from app.main import app
from app.routers import ingest as ingest_mod
from app.routers import deps as deps_mod
from app.database import Base, Transaction, User, get_db

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

SECRET = os.environ["WEBHOOK_SECRET"]
ITEM = {
    "title": "招商银行",
    "body": "您尾号***1234消费88.00元，商户星巴克",
    "source": "cmb",
    "timestamp": "2026-07-28T15:00:00+08:00",
}
PARSED = {
    "amount": 88.0,
    "category": "餐饮",
    "account": "cmb",
    "transaction_type": "expense",
    "description": "星巴克",
    "raw_text": "raw",
    "confidence": 0.9,
}


class FakeResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return dict(PARSED)


class FakeParserClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return FakeResp()


class DeadParserClient(FakeParserClient):
    async def post(self, *a, **k):
        raise httpx.ConnectError("parser down")


async def _noop(*a, **k):
    return None


def sign_headers(item, event_id=None, secret=SECRET, ts=None):
    body = json.dumps(item, ensure_ascii=False).encode("utf-8")
    ts = ts or str(int(time.time()))
    eid = event_id or f"t-{ts}-1"
    sig = "sha256=" + hmac.new(
        secret.encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Silentbook-Timestamp": ts,
        "X-Silentbook-Event-Id": eid,
        "X-Silentbook-Signature": sig,
    }
    return headers, body


def tx_count():
    """测试线程 tenant 为空会被隔离到 user_id=-1，计数前显式切到 webhook 用户。"""
    from app.tenant import reset_tenant_user_id, set_tenant_user_id

    tok = set_tenant_user_id(1)
    try:
        with TestingSessionLocal() as db:
            return db.query(Transaction).count()
    finally:
        reset_tenant_user_id(tok)


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    Base.metadata.create_all(bind=engine)
    # fixture 级覆盖：不用模块级全局覆盖，避免污染同进程其他测试文件；
    # teardown 时恢复原值（其他文件可能是模块级覆盖）
    prev_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(httpx, "AsyncClient", FakeParserClient)
    monkeypatch.setattr(ingest_mod, "_background_push_and_analyze", _noop)
    monkeypatch.setattr(deps_mod, "_check_low_balance_alert", _noop)
    with TestingSessionLocal() as db:
        db.add(
            User(
                email="wh@test.local",
                password_hash="x",
                nickname="t",
                is_active=True,
            )
        )
        db.commit()
    yield
    Base.metadata.drop_all(bind=engine)
    if prev_override is not None:
        app.dependency_overrides[get_db] = prev_override
    else:
        app.dependency_overrides.pop(get_db, None)


def test_create_ok():
    h, body = sign_headers(ITEM, event_id="e-1")
    r = client.post("/webhook/notify", content=body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "created"
    assert tx_count() == 1


def test_retry_new_event_id_is_duplicate_not_double_ledger():
    h, body = sign_headers(ITEM, event_id="e-1")
    assert client.post("/webhook/notify", content=body, headers=h).status_code == 200
    h2, body2 = sign_headers(ITEM, event_id="e-2")
    r2 = client.post("/webhook/notify", content=body2, headers=h2)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "duplicate"
    assert tx_count() == 1


def test_replay_same_event_id_409():
    h, body = sign_headers(ITEM, event_id="e-1")
    assert client.post("/webhook/notify", content=body, headers=h).status_code == 200
    h2, body2 = sign_headers(
        {**ITEM, "body": "您尾号***1234消费99.00元，商户瑞幸"},
        event_id="e-1",
    )
    r2 = client.post("/webhook/notify", content=body2, headers=h2)
    assert r2.status_code == 409


def test_bad_signature_401():
    h, body = sign_headers(ITEM, event_id="e-1", secret="wrong-secret")
    assert client.post("/webhook/notify", content=body, headers=h).status_code == 401
    assert tx_count() == 0


def test_stale_timestamp_401():
    h, body = sign_headers(ITEM, event_id="e-1", ts=str(int(time.time()) - 600))
    assert client.post("/webhook/notify", content=body, headers=h).status_code == 401
    assert tx_count() == 0


def test_batch_per_item_dedupe():
    items = [ITEM, {**ITEM, "body": "您尾号***1234消费15.00元，商户瑞幸"}]
    raw = json.dumps(items, ensure_ascii=False).encode("utf-8")
    ts = str(int(time.time()))
    sig = "sha256=" + hmac.new(
        SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    h = {
        "Content-Type": "application/json",
        "X-Silentbook-Timestamp": ts,
        "X-Silentbook-Event-Id": "batch-1",
        "X-Silentbook-Signature": sig,
    }
    r = client.post("/webhook/notify/batch", content=raw, headers=h)
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()["results"]] == ["created", "created"]
    assert tx_count() == 2

    # 整批换新 outer event_id 重试：逐条判重，不重记
    h["X-Silentbook-Event-Id"] = "batch-2"
    r2 = client.post("/webhook/notify/batch", content=raw, headers=h)
    assert r2.status_code == 200, r2.text
    assert [x["status"] for x in r2.json()["results"]] == ["duplicate", "duplicate"]
    assert tx_count() == 2


def test_parser_down_returns_503(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", DeadParserClient)
    h, body = sign_headers(ITEM, event_id="e-9")
    r = client.post("/webhook/notify", content=body, headers=h)
    assert r.status_code == 503
    assert tx_count() == 0
