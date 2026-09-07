"""V2-006 三级分类预算 - 测试套件"""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_budgets_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

import pytest
import json
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_mod
from app.main import app
from app.database import Base, get_db, Setting, Transaction

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
        json={"email": "budgets@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    j = r.json()
    yield {"headers": {"Authorization": f"Bearer {j['access_token']}"}, "user_id": j["user"]["id"]}
    Base.metadata.drop_all(bind=engine)
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def add_txs(uid, txs):
    db = TestingSessionLocal()
    try:
        for tx in txs:
            tx = dict(tx)
            tx.setdefault("user_id", uid)
            db.add(Transaction(**tx))
        db.commit()
    finally:
        db.close()


class TestBudgetCRUD:

    def test_create_budget_with_level(self, auth):
        resp = client.post("/budgets", json={
            "category": "餐饮",
            "monthly_limit": 3000,
            "alert_threshold": 0.8,
            "level": "L1"
        }, headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "budgets" in data
        budget = data["budgets"][0]
        assert budget["category"] == "餐饮"
        assert budget["level"] == "L1"

    def test_create_budget_default_level(self, auth):
        resp = client.post("/budgets", json={
            "category": "健身",
            "monthly_limit": 500,
        }, headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        budget = resp.json()["budgets"][0]
        assert budget["level"] == "L2"

    def test_create_budget_invalid_level(self, auth):
        resp = client.post("/budgets", json={
            "category": "娱乐",
            "monthly_limit": 200,
            "level": "L4"
        }, headers=auth["headers"])
        assert resp.status_code == 422

    def test_get_budgets_returns_level(self, auth):
        client.post("/budgets", json={
            "category": "房租", "monthly_limit": 5000, "level": "L1"
        }, headers=auth["headers"])
        client.post("/budgets", json={
            "category": "咖啡", "monthly_limit": 300, "level": "L2"
        }, headers=auth["headers"])
        client.post("/budgets", json={
            "category": "游戏", "monthly_limit": 100, "level": "L3"
        }, headers=auth["headers"])

        resp = client.get("/budgets", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        budgets = resp.json()
        assert len(budgets) == 3
        levels = {b["category"]: b["level"] for b in budgets}
        assert levels["房租"] == "L1"
        assert levels["咖啡"] == "L2"
        assert levels["游戏"] == "L3"

    def test_update_existing_budget_keeps_level(self, auth):
        client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 3000, "level": "L1"
        }, headers=auth["headers"])
        client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 3500, "level": "L1"
        }, headers=auth["headers"])
        resp = client.get("/budgets", headers=auth["headers"])
        budget = [b for b in resp.json() if b["category"] == "餐饮"][0]
        assert budget["monthly_limit"] == 3500
        assert budget["level"] == "L1"

    def test_delete_budget(self, auth):
        client.post("/budgets", json={
            "category": "娱乐", "monthly_limit": 200, "level": "L3"
        }, headers=auth["headers"])
        resp = client.delete("/budgets/娱乐", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        resp2 = client.get("/budgets", headers=auth["headers"])
        assert len(resp2.json()) == 0


class TestBudgetLevels:

    def test_empty_budgets_returns_zero(self, auth):
        resp = client.get("/budgets/levels", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total_budget"] == 0
        assert data["total_spent"] == 0
        assert "L1" in data["levels"]
        assert "L2" in data["levels"]
        assert "L3" in data["levels"]
        assert data["levels"]["L1"]["label"] == "必要支出"
        assert data["levels"]["L2"]["label"] == "改善支出"
        assert data["levels"]["L3"]["label"] == "非必要支出"

    def test_levels_with_budgets_only(self, auth):
        client.post("/budgets", json={
            "category": "房租", "monthly_limit": 5000, "level": "L1"
        }, headers=auth["headers"])
        client.post("/budgets", json={
            "category": "健身", "monthly_limit": 500, "level": "L2"
        }, headers=auth["headers"])
        client.post("/budgets", json={
            "category": "游戏", "monthly_limit": 100, "level": "L3"
        }, headers=auth["headers"])

        resp = client.get("/budgets/levels", headers=auth["headers"])
        data = resp.json()
        assert data["total_budget"] == 5600
        assert data["levels"]["L1"]["budget_total"] == 5000
        assert data["levels"]["L2"]["budget_total"] == 500
        assert data["levels"]["L3"]["budget_total"] == 100

    def test_levels_with_spending(self, auth):
        uid = auth["user_id"]
        client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 3000, "level": "L1"
        }, headers=auth["headers"])
        client.post("/budgets", json={
            "category": "健身", "monthly_limit": 500, "level": "L2"
        }, headers=auth["headers"])
        client.post("/budgets", json={
            "category": "游戏", "monthly_limit": 100, "level": "L3"
        }, headers=auth["headers"])

        txs = [
            dict(amount=200, category="餐饮", account="微信",
                 transaction_type="expense", parsed_at=datetime.utcnow()),
            dict(amount=50, category="餐饮", account="微信",
                 transaction_type="expense", parsed_at=datetime.utcnow()),
            dict(amount=300, category="健身", account="支付宝",
                 transaction_type="expense", parsed_at=datetime.utcnow()),
            dict(amount=80, category="游戏", account="微信",
                 transaction_type="expense", parsed_at=datetime.utcnow()),
        ]
        add_txs(uid, txs)

        resp = client.get("/budgets/levels", headers=auth["headers"])
        data = resp.json()

        assert data["levels"]["L1"]["spent_total"] == 250
        assert data["levels"]["L1"]["budget_total"] == 3000
        assert data["levels"]["L2"]["spent_total"] == 300
        assert data["levels"]["L2"]["budget_total"] == 500
        assert data["levels"]["L3"]["spent_total"] == 80
        assert data["levels"]["L3"]["budget_total"] == 100

    def test_unbudgeted_spending_by_default_mapping(self, auth):
        uid = auth["user_id"]
        client.post("/budgets", json={
            "category": "房租", "monthly_limit": 5000, "level": "L1"
        }, headers=auth["headers"])

        add_txs(uid, [dict(amount=100, category="餐饮", account="微信",
                            transaction_type="expense", parsed_at=datetime.utcnow())])

        resp = client.get("/budgets/levels", headers=auth["headers"])
        data = resp.json()
        assert data["levels"]["L1"]["spent_total"] == 100
        assert data["levels"]["L1"]["unbudgeted_spent"] == 100

    def test_over_budget_alert(self, auth):
        uid = auth["user_id"]
        client.post("/budgets", json={
            "category": "游戏", "monthly_limit": 100,
            "alert_threshold": 0.8, "level": "L3"
        }, headers=auth["headers"])

        add_txs(uid, [dict(amount=90, category="游戏", account="微信",
                            transaction_type="expense", parsed_at=datetime.utcnow())])

        resp = client.get("/budgets/levels", headers=auth["headers"])
        data = resp.json()
        item = data["levels"]["L3"]["items"][0]
        assert item["alert"] is True
        assert item["usage_rate"] == 90.0

    def test_level_compressibility_labels(self, auth):
        resp = client.get("/budgets/levels", headers=auth["headers"])
        data = resp.json()
        assert data["levels"]["L1"]["compressibility"] == "<10%"
        assert data["levels"]["L2"]["compressibility"] == "30-50%"
        assert data["levels"]["L3"]["compressibility"] == "80-100%"


class TestDefaultCategoryMapping:

    def test_known_categories_mapped(self, auth):
        uid = auth["user_id"]
        txs = [
            dict(amount=100, category="房租", account="",
                 transaction_type="expense", parsed_at=datetime.utcnow()),
            dict(amount=200, category="学习", account="",
                 transaction_type="expense", parsed_at=datetime.utcnow()),
            dict(amount=50, category="游戏", account="",
                 transaction_type="expense", parsed_at=datetime.utcnow()),
        ]
        add_txs(uid, txs)

        resp = client.get("/budgets/levels", headers=auth["headers"])
        data = resp.json()
        assert data["levels"]["L1"]["unbudgeted_spent"] == 100
        assert data["levels"]["L2"]["unbudgeted_spent"] == 200
        assert data["levels"]["L3"]["unbudgeted_spent"] == 50

    def test_unknown_category_defaults_l2(self, auth):
        uid = auth["user_id"]
        add_txs(uid, [dict(amount=77, category="奇葩分类", account="",
                            transaction_type="expense", parsed_at=datetime.utcnow())])

        resp = client.get("/budgets/levels", headers=auth["headers"])
        data = resp.json()
        assert data["levels"]["L2"]["unbudgeted_spent"] == 77


class TestBackwardCompat:

    def test_old_budget_data_without_level(self, auth):
        uid = auth["user_id"]
        db = TestingSessionLocal()
        try:
            db.add(Setting(key="budgets", value=json.dumps([
                {"category": "房租", "monthly_limit": 5000, "alert_threshold": 0.8},
                {"category": "游戏", "monthly_limit": 200, "alert_threshold": 0.8},
            ]), user_id=uid))
            db.commit()
        finally:
            db.close()

        resp = client.get("/budgets/levels", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["levels"]["L1"]["budget_total"] == 5000
        assert data["levels"]["L3"]["budget_total"] == 200

    def test_existing_endpoints_work(self, auth):
        resp = client.get("/budgets", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

        resp = client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 2000
        }, headers=auth["headers"])
        assert resp.status_code == 200, resp.text

        resp = client.get("/budgets", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
        budgets = resp.json()
        assert len(budgets) == 1
        assert budgets[0]["category"] == "餐饮"
        assert budgets[0]["level"] == "L2"

        resp = client.delete("/budgets/餐饮", headers=auth["headers"])
        assert resp.status_code == 200, resp.text
