"""Coverage boost tests - target uncovered endpoints in main.py"""
import itertools
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

from cryptography.fernet import Fernet
os.environ.setdefault("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

import app.main as main_mod
from app.main import app
from app.database import Base, Transaction, Setting, Account, Asset, Liability, get_db, User  # noqa: F401
from app.auth import hash_password  # noqa: F401

main_mod.RATE_LIMIT_ENABLED = False

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)

_email_counter = itertools.count()


@pytest.fixture()
def auth():
    Base.metadata.create_all(bind=engine)
    prev_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    r = client.post(
        "/auth/register",
        json={"email": f"cov{next(_email_counter)}@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    yield {"h": {"Authorization": f"Bearer {body['access_token']}"}, "uid": body["user"]["id"]}
    Base.metadata.drop_all(bind=engine)
    if prev_override is not None:
        app.dependency_overrides[get_db] = prev_override
    else:
        app.dependency_overrides.pop(get_db, None)


def _signed_post(path, payload, event_id, secret=None):
    import hmac as _hmac
    import hashlib as _hl
    import json as _json
    import time as _time
    s = secret or "test-shared-secret-0123456789abcdef"
    body = _json.dumps(payload, ensure_ascii=False).encode()
    ts = str(int(_time.time()))
    sig = "sha256=" + _hmac.new(s.encode(), f"{ts}.".encode() + body, _hl.sha256).hexdigest()
    return client.post(path, content=body, headers={
        "Content-Type": "application/json",
        "X-Silentbook-Timestamp": ts,
        "X-Silentbook-Event-Id": event_id,
        "X-Silentbook-Signature": sig,
    })


class TestTransactionCRUD:
    def test_create_transaction(self, auth):
        r = client.post("/transactions", json={
            "amount": 50.0, "category": "餐饮", "transaction_type": "expense",
            "account": "现金", "parsed_at": datetime.now().isoformat()
        }, headers=auth["h"])
        assert r.status_code == 200, r.text
        assert r.json()["amount"] == 50.0

    def test_list_transactions(self, auth):
        with TestingSessionLocal() as db:
            tx = Transaction(amount=30, category="餐饮", transaction_type="expense",
                             account="现金", parsed_at=datetime.now(), user_id=auth["uid"])
            db.add(tx); db.commit()
        r = client.get("/transactions", headers=auth["h"])
        assert r.status_code == 200, r.text
        assert len(r.json()) >= 1

    def test_get_transaction(self, auth):
        with TestingSessionLocal() as db:
            tx = Transaction(amount=30, category="餐饮", transaction_type="expense",
                             account="现金", parsed_at=datetime.now(), user_id=auth["uid"])
            db.add(tx); db.commit()
            tx_id = tx.id
        r = client.get(f"/transactions/{tx_id}", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_update_transaction(self, auth):
        with TestingSessionLocal() as db:
            tx = Transaction(amount=30, category="餐饮", transaction_type="expense",
                             account="现金", parsed_at=datetime.now(), user_id=auth["uid"])
            db.add(tx); db.commit()
            tx_id = tx.id
        r = client.put(f"/transactions/{tx_id}", json={"amount": 99.0}, headers=auth["h"])
        assert r.status_code == 200, r.text
        assert r.json()["amount"] == 99.0

    def test_delete_transaction(self, auth):
        with TestingSessionLocal() as db:
            tx = Transaction(amount=30, category="餐饮", transaction_type="expense",
                             account="现金", parsed_at=datetime.now(), user_id=auth["uid"])
            db.add(tx); db.commit()
            tx_id = tx.id
        r = client.delete(f"/transactions/{tx_id}", headers=auth["h"])
        assert r.status_code == 200, r.text


class TestParseAndWebhook:
    def test_parse_text(self, auth):
        r = client.post("/parse", json={"text": "微信支付 餐饮 -30.00"}, headers=auth["h"])
        # 外部解析器不可用时返回 502/503
        assert r.status_code in [200, 502, 503], r.text

    def test_webhook_notify(self, auth):
        r = _signed_post("/webhook/notify", {
            "title": "微信支付",
            "body": "微信支付 餐饮 30.00元",
            "source": "wechat",
        }, "cov-wh-1")
        # 外部解析器不可用时为 503；签名/归属无误即算链路通
        assert r.status_code in [200, 502, 503], r.text

    def test_webhook_notify_batch(self, auth):
        import json as _json
        import hmac as _hmac
        import hashlib as _hl
        import time as _time
        items = [{"title": "微信支付", "body": "微信支付 餐饮 30.00元", "source": "wechat"}]
        body = _json.dumps(items, ensure_ascii=False).encode()
        ts = str(int(_time.time()))
        s = "test-shared-secret-0123456789abcdef"
        sig = "sha256=" + _hmac.new(s.encode(), f"{ts}.".encode() + body, _hl.sha256).hexdigest()
        r = client.post("/webhook/notify/batch", content=body, headers={
            "Content-Type": "application/json",
            "X-Silentbook-Timestamp": ts,
            "X-Silentbook-Event-Id": "cov-wh-batch-1",
            "X-Silentbook-Signature": sig,
        })
        assert r.status_code in [200, 502, 503], r.text
        if r.status_code == 200:
            assert r.json()["total"] == 1


class TestStatsEndpoints:
    def _add_sample_data(self, uid):
        with TestingSessionLocal() as db:
            for i in range(5):
                tx = Transaction(amount=50 + i * 10, category="餐饮", transaction_type="expense",
                                 account="现金", parsed_at=datetime.now() - timedelta(days=i * 3),
                                 user_id=uid)
                db.add(tx)
            db.commit()

    def test_dashboard_stats(self, auth):
        self._add_sample_data(auth["uid"])
        r = client.get("/stats/dashboard", headers=auth["h"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert "net_assets" in data

    def test_stats_trend(self, auth):
        self._add_sample_data(auth["uid"])
        r = client.get("/stats/trend", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_stats_monthly(self, auth):
        self._add_sample_data(auth["uid"])
        r = client.get("/stats/monthly", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_stats_daily(self, auth):
        self._add_sample_data(auth["uid"])
        r = client.get("/stats/daily", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_stats_weekly(self, auth):
        self._add_sample_data(auth["uid"])
        r = client.get("/stats/weekly", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_stats_yearly(self, auth):
        self._add_sample_data(auth["uid"])
        r = client.get("/stats/yearly", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_stats_asset_curve(self, auth):
        self._add_sample_data(auth["uid"])
        r = client.get("/stats/asset-curve", headers=auth["h"])
        assert r.status_code == 200, r.text


class TestExportImport:
    def test_export_csv(self, auth):
        with TestingSessionLocal() as db:
            tx = Transaction(amount=30, category="餐饮", transaction_type="expense",
                             account="现金", parsed_at=datetime.now(), user_id=auth["uid"])
            db.add(tx); db.commit()
        r = client.get("/export/csv", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_import_csv(self, auth):
        csv_content = (
            "日期,类型,金额,分类,账户,描述,置信度\n"
            "2026-07-01 10:00,expense,50.0,餐饮,现金,午饭,1.0\n"
        )
        r = client.post("/import/csv", json={"content": csv_content}, headers=auth["h"])
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 1


class TestSettingsEndpoints:
    def test_get_settings_empty(self, auth):
        r = client.get("/settings", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_put_settings(self, auth):
        r = client.put("/settings", json={"monthly_income": 15000, "currency": "CNY"}, headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_get_settings_after_put(self, auth):
        client.put("/settings", json={"monthly_income": 15000}, headers=auth["h"])
        r = client.get("/settings", headers=auth["h"])
        assert r.status_code == 200, r.text


class TestOnboardingAndAuth:
    def test_onboarding_status(self, auth):
        pytest.skip("路由 /onboarding/status 已不存在（routers 中无 onboarding 模块）")

    def test_auth_status(self, auth):
        pytest.skip("路由 /auth/status 已不存在（现为 /auth/me，需登录）")


class TestSchedulerEndpoints:
    def test_scheduler_status(self, auth):
        # 调度器只在 lifespan 启动时创建，普通 TestClient 下 _scheduler 为 None；
        # 本用例单独进 lifespan 驗证真实状态。
        with TestClient(app) as c:
            r = c.get("/scheduler/status", headers=auth["h"])
            assert r.status_code == 200, r.text
            assert r.json()["running"] is True


class TestAssetCRUD:
    def test_create_asset(self, auth):
        r = client.post("/assets", json={
            "name": "基金A", "asset_type": "fund", "current_value": 10000,
            "initial_value": 9000
        }, headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_list_assets(self, auth):
        r = client.get("/assets", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_update_asset(self, auth):
        with TestingSessionLocal() as db:
            asset = Asset(name="基金A", asset_type="fund", current_value=10000,
                          initial_value=9000, status="active", user_id=auth["uid"])
            db.add(asset); db.commit()
            asset_id = asset.id
        r = client.put(f"/assets/{asset_id}", json={"current_value": 11000}, headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_delete_asset(self, auth):
        with TestingSessionLocal() as db:
            asset = Asset(name="基金A", asset_type="fund", current_value=10000,
                          initial_value=9000, status="active", user_id=auth["uid"])
            db.add(asset); db.commit()
            asset_id = asset.id
        r = client.delete(f"/assets/{asset_id}", headers=auth["h"])
        assert r.status_code == 200, r.text


class TestLiabilityCRUD:
    def test_create_liability(self, auth):
        r = client.post("/liabilities", json={
            "name": "房贷", "liability_type": "mortgage",
            "total_amount": 1000000, "current_amount": 900000,
            "interest_rate": 4.5, "monthly_payment": 5500
        }, headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_list_liabilities(self, auth):
        r = client.get("/liabilities", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_liabilities_summary(self, auth):
        r = client.get("/liabilities/summary", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_debt_ratio(self, auth):
        r = client.get("/liabilities/debt-ratio", headers=auth["h"])
        assert r.status_code == 200, r.text


class TestGoalEndpoints:
    def test_goals_summary_empty(self, auth):
        r = client.get("/goals/summary", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_create_goal(self, auth):
        r = client.post("/goals", json={
            "name": "应急基金", "goal_type": "savings",
            "target_amount": 50000, "current_amount": 10000,
            "deadline": "2027-12-31"
        }, headers=auth["h"])
        assert r.status_code == 201, r.text

    def test_list_goals(self, auth):
        r = client.get("/goals", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_goal_crud_flow(self, auth):
        h = auth["h"]
        # Create
        r = client.post("/goals", json={
            "name": "旅行基金", "goal_type": "savings",
            "target_amount": 20000, "current_amount": 5000,
            "priority": "medium", "status": "active"
        }, headers=h)
        assert r.status_code == 201, r.text
        goal_id = r.json().get("id") or r.json().get("goal_id")
        if not goal_id:
            return  # Skip if can't get ID

        # Read
        r = client.get(f"/goals/{goal_id}", headers=h)
        assert r.status_code == 200, r.text

        # Update
        r = client.put(f"/goals/{goal_id}", json={"current_amount": 8000}, headers=h)
        assert r.status_code == 200, r.text

        # Contribute
        r = client.post(f"/goals/{goal_id}/contribute", json={"amount": 1000}, headers=h)
        assert r.status_code == 200, r.text

        # Contributions history
        r = client.get(f"/goals/{goal_id}/contributions", headers=h)
        assert r.status_code == 200, r.text

        # Delete
        r = client.delete(f"/goals/{goal_id}", headers=h)
        assert r.status_code == 200, r.text


class TestBackupEndpoints:
    def test_backup_create(self, auth):
        r = client.post("/backup/create", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_backup_list(self, auth):
        r = client.get("/backup/list", headers=auth["h"])
        assert r.status_code == 200, r.text

    def test_backup_status(self, auth):
        r = client.get("/backup/status", headers=auth["h"])
        assert r.status_code == 200, r.text


class TestDeleteTransactions:
    def test_delete_all_transactions(self, auth):
        with TestingSessionLocal() as db:
            for i in range(3):
                tx = Transaction(amount=30, category="餐饮", transaction_type="expense",
                                 account="现金", parsed_at=datetime.now(), user_id=auth["uid"])
                db.add(tx)
            db.commit()
        r = client.delete("/transactions?confirm=true", headers=auth["h"])
        assert r.status_code == 200, r.text
