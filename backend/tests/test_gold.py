"""金价接口回归：NameError 500 永不复发；全源失败走 503 而非 500。"""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_gold_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

from fastapi.testclient import TestClient

import app.main as main_mod
from app.main import app
from app import gold as gold_mod

main_mod.RATE_LIMIT_ENABLED = False

client = TestClient(app, raise_server_exceptions=False)


def test_gold_price_mocked_ok(monkeypatch):
    async def fake_quote():
        return {"price": 1028.5, "source": "TEST"}

    monkeypatch.setattr(gold_mod, "fetch_gold_quote", fake_quote)
    gold_mod_path = "app.routers.assets.fetch_gold_quote"
    import app.routers.assets as assets_mod

    monkeypatch.setattr(assets_mod, "fetch_gold_quote", fake_quote)
    r = client.get("/gold-price")
    assert r.status_code == 200, r.text
    assert r.json()["price"] == 1028.5


def test_gold_price_all_sources_down_is_503_not_500(monkeypatch):
    async def fake_none():
        return None

    import app.routers.assets as assets_mod

    monkeypatch.setattr(assets_mod, "fetch_gold_quote", fake_none)
    # 清缓存，保证走到抓取分支
    from app.routers.assets import _GOLD_CACHE

    _GOLD_CACHE.clear()
    r = client.get("/gold-price")
    assert r.status_code == 503, r.text


def test_gold_price_never_500_live():
    """实网（无 mock）：要么 200 要么 503，绝不能 500（NameError 回归）。"""
    from app.routers.assets import _GOLD_CACHE

    _GOLD_CACHE.clear()
    r = client.get("/gold-price")
    assert r.status_code in (200, 503), r.text
