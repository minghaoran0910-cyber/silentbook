"""FX 汇率：主备切换、缓存、stale 降级测试."""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_fx_test.db"
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
from app.routers import fx as fx_mod
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


class FakeResp:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self._text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPStatusError("bad", request=None, response=self)

    def json(self):
        return self._payload

    @property
    def text(self):
        return self._text


def frankfurter_ok(*a, **k):
    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp({"rates": {"USD": 0.14, "EUR": 0.12}, "date": "2026-09-04"})

    return C()


def frankfurter_list_shape(*a, **k):
    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp([{"base": "CNY", "quote": "USD", "rate": 0.14}])

    return C()


def all_dead(*a, **k):
    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("down")

    return C()


def sina_ok(*a, **k):
    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            url = k.get("params", "")
            if "frankfurter" in str(a):
                raise httpx.ConnectError("frankfurter down")
            return FakeResp(
                text='var hq_str_fx_susdcny="美元人民币,7.10,7.11,7.105,0,0,0,0,美元人民币,2026-09-04";'
            )

    return C()


@pytest.fixture()
def auth():
    Base.metadata.create_all(bind=engine)
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    fx_mod._fx_cache.update({"at": 0.0, "date": "", "rates": {}, "source": ""})
    r = client.post(
        "/auth/register",
        json={"email": "fx@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    Base.metadata.drop_all(bind=engine)
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def test_frankfurter_ok(auth, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", frankfurter_ok)
    r = client.get("/fx/rates?base=CNY&quotes=USD,EUR", headers=auth)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["rates"] == {"USD": 0.14, "EUR": 0.12}
    assert d["source"] == "frankfurter" and d["stale"] is False


def test_frankfurter_list_shape(auth, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", frankfurter_list_shape)
    r = client.get("/fx/rates?base=CNY&quotes=USD", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["rates"] == {"USD": 0.14}


def test_fallback_to_sina(auth, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", sina_ok)
    r = client.get("/fx/rates?base=CNY&quotes=USD", headers=auth)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["source"] == "sina"
    assert abs(d["rates"]["USD"] - round(1 / 7.105, 6)) < 1e-9


def test_both_down_no_cache_503(auth, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", all_dead)
    r = client.get("/fx/rates?base=CNY&quotes=USD", headers=auth)
    assert r.status_code == 503


def test_both_down_with_cache_stale(auth, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", frankfurter_ok)
    assert client.get("/fx/rates?base=CNY&quotes=USD", headers=auth).status_code == 200
    # 缓存过期后双源全挂 → 回最后快照并标记 stale
    fx_mod._fx_cache["at"] = 0.0
    monkeypatch.setattr(httpx, "AsyncClient", all_dead)
    r = client.get("/fx/rates?base=CNY&quotes=USD", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["stale"] is True


def test_unsupported_quotes_400(auth):
    r = client.get("/fx/rates?base=CNY&quotes=XXX", headers=auth)
    assert r.status_code == 400


def test_currencies(auth):
    r = client.get("/fx/currencies", headers=auth)
    assert r.status_code == 200, r.text
    assert "USD" in r.json()["supported"]
