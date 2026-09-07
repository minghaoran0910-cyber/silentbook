"""V2-010 现金流预测测试"""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_forecast_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

import pytest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_mod
from app.main import app
from app.database import Base, get_db, Transaction

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
        json={"email": "forecast@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    j = r.json()
    yield {"headers": {"Authorization": f"Bearer {j['access_token']}"}, "user_id": j["user"]["id"]}
    Base.metadata.drop_all(bind=engine)
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def add_one(uid, amount, category, account, tx_type, parsed_at):
    db = TestingSessionLocal()
    try:
        db.add(Transaction(
            amount=amount, category=category, account=account,
            transaction_type=tx_type, confidence=1.0,
            parsed_at=parsed_at, user_id=uid,
        ))
        db.commit()
    finally:
        db.close()


def add_many(uid, n, **kw):
    db = TestingSessionLocal()
    try:
        for _ in range(n):
            db.add(Transaction(user_id=uid, **kw))
        db.commit()
    finally:
        db.close()


class TestCashflowForecast:

    def test_empty_data(self, auth):
        response = client.get("/cashflow/forecast", headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["forecast_days"] == 30
        assert data["summary"]["predicted_total_income"] == 0
        assert data["summary"]["predicted_total_expense"] == 0
        assert data["summary"]["predicted_net"] == 0
        assert data["summary"]["confidence"] == "low"
        assert data["summary"]["history_transaction_count"] == 0
        assert data["summary"]["recurring_count"] == 0
        assert len(data["daily_forecast"]) == 0
        assert data["recurring_items"] == []

    def test_forecast_days_param(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(25):
                db.add(Transaction(
                    amount=50, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"days": 7}, headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["forecast_days"] == 7
        assert len(data["daily_forecast"]) == 7

    def test_recurring_detection(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for months_ago in range(3):
                d = now - timedelta(days=months_ago * 30 + 15)
                db.add(Transaction(
                    amount=10000, category="工资", account="招商",
                    transaction_type="income", confidence=1.0,
                    parsed_at=d, user_id=uid,
                ))
            for months_ago in range(3):
                d = now - timedelta(days=months_ago * 30 + 1)
                db.add(Transaction(
                    amount=3000, category="房租", account="招商",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=d, user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"history_days": 120}, headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["summary"]["recurring_count"] == 2
        recurring_cats = [item["category"] for item in data["recurring_items"]]
        assert "工资" in recurring_cats
        assert "房租" in recurring_cats

    def test_non_recurring_daily_average(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(90):
                db.add(Transaction(
                    amount=30, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"history_days": 90, "days": 10}, headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["summary"]["avg_daily_expense"] == 30.0
        for day in data["daily_forecast"]:
            assert day["predicted_expense"] >= 30.0

    def test_recurring_placed_on_correct_day(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for months_ago in range(3):
                d = now.replace(day=15) - timedelta(days=months_ago * 30)
                if d > now:
                    d = d - timedelta(days=30)
                db.add(Transaction(
                    amount=5000, category="工资", account="招商",
                    transaction_type="income", confidence=1.0,
                    parsed_at=d, user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"history_days": 120, "days": 31}, headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()

        # 固定项应被检测到，且落在检测到的 day_of_month 那天（避免写死15号导致月长波动）
        assert data["summary"]["recurring_count"] == 1
        dom = data["recurring_items"][0]["day_of_month"]
        target = [d for d in data["daily_forecast"] if d["day"] == dom]
        assert target, f"forecast missing dom={dom}"
        assert target[0]["recurring_income"] == 5000.0

    def test_confidence_low(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(5):
                db.add(Transaction(
                    amount=50, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"history_days": 10}, headers=auth["headers"])
        data = response.json()
        assert data["summary"]["confidence"] == "low"

    def test_confidence_medium(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(25):
                db.add(Transaction(
                    amount=50, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"history_days": 30}, headers=auth["headers"])
        data = response.json()
        assert data["summary"]["confidence"] == "medium"

    def test_confidence_high(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(60):
                db.add(Transaction(
                    amount=50, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"history_days": 90}, headers=auth["headers"])
        data = response.json()
        assert data["summary"]["confidence"] == "high"

    def test_account_filter(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(20):
                db.add(Transaction(
                    amount=100, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
                db.add(Transaction(
                    amount=200, category="餐饮", account="招商",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"account": "微信", "history_days": 30}, headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["account"] == "微信"
        assert data["summary"]["avg_daily_expense"] > 60
        assert data["summary"]["avg_daily_expense"] < 70

    def test_forecast_starts_from_tomorrow(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        add_one(uid, 100, "test", "微信", "expense", now)

        response = client.get("/cashflow/forecast", params={"days": 3, "history_days": 5}, headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()

        assert len(data["daily_forecast"]) == 3
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        assert data["daily_forecast"][0]["date"] == tomorrow

    def test_daily_forecast_fields(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(10):
                db.add(Transaction(
                    amount=50, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"days": 5, "history_days": 15}, headers=auth["headers"])
        data = response.json()

        assert len(data["daily_forecast"]) == 5
        for day in data["daily_forecast"]:
            assert "date" in day
            assert "day" in day
            assert "weekday" in day
            assert "predicted_income" in day
            assert "predicted_expense" in day
            assert "predicted_net" in day
            assert "recurring_income" in day
            assert "recurring_expense" in day

    def test_summary_fields(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(10):
                db.add(Transaction(
                    amount=50, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"days": 5, "history_days": 15}, headers=auth["headers"])
        data = response.json()

        s = data["summary"]
        assert "predicted_total_income" in s
        assert "predicted_total_expense" in s
        assert "predicted_net" in s
        assert "avg_daily_income" in s
        assert "avg_daily_expense" in s
        assert "recurring_count" in s
        assert "confidence" in s
        assert "history_transaction_count" in s

    def test_recurring_with_variable_amount(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        amounts = [3000, 3100, 2950]
        db = TestingSessionLocal()
        try:
            for i, amt in enumerate(amounts):
                d = now - timedelta(days=i * 30 + 5)
                db.add(Transaction(
                    amount=amt, category="房租", account="招商",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=d, user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"history_days": 120}, headers=auth["headers"])
        data = response.json()

        assert data["summary"]["recurring_count"] == 1
        item = data["recurring_items"][0]
        assert item["category"] == "房租"
        assert 2950 <= item["amount"] <= 3100

    def test_non_recurring_not_detected_as_recurring(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(3):
                db.add(Transaction(
                    amount=10 + i * 500, category="购物", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i * 30 + 10), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"history_days": 120}, headers=auth["headers"])
        data = response.json()

        assert data["summary"]["recurring_count"] == 0

    def test_income_and_expense_forecast(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(30):
                db.add(Transaction(
                    amount=100, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
                db.add(Transaction(
                    amount=300, category="兼职", account="支付宝",
                    transaction_type="income", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"days": 10, "history_days": 30}, headers=auth["headers"])
        data = response.json()

        assert data["summary"]["avg_daily_income"] == 300.0
        assert data["summary"]["avg_daily_expense"] == 100.0
        for day in data["daily_forecast"]:
            assert day["predicted_net"] == 200.0

    def test_total_calculation(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        db = TestingSessionLocal()
        try:
            for i in range(20):
                db.add(Transaction(
                    amount=50, category="餐饮", account="微信",
                    transaction_type="expense", confidence=1.0,
                    parsed_at=now - timedelta(days=i), user_id=uid,
                ))
            db.commit()
        finally:
            db.close()

        response = client.get("/cashflow/forecast", params={"days": 10, "history_days": 25}, headers=auth["headers"])
        data = response.json()

        total_from_daily = sum(d["predicted_expense"] for d in data["daily_forecast"])
        assert abs(data["summary"]["predicted_total_expense"] - total_from_daily) < 0.1

    def test_history_days_param(self, auth):
        uid = auth["user_id"]
        now = datetime.utcnow()
        add_one(uid, 100, "test", "微信", "expense", now - timedelta(days=10))
        add_one(uid, 200, "test", "微信", "expense", now - timedelta(days=50))

        response = client.get("/cashflow/forecast", params={"history_days": 30, "days": 5}, headers=auth["headers"])
        data = response.json()
        assert data["summary"]["history_transaction_count"] == 1

        response = client.get("/cashflow/forecast", params={"history_days": 60, "days": 5}, headers=auth["headers"])
        data = response.json()
        assert data["summary"]["history_transaction_count"] == 2
