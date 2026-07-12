"""V2-039: 交易列表垃圾过滤视图 - hide_noise 参数测试"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, Transaction
from app.main import app


TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def auth_headers():
    # Register
    client.post("/auth/register", json={
        "email": "test@example.com",
        "password": "testpass123"
    })
    # Login
    resp = client.post("/auth/login", json={
        "account": "test@example.com",
        "password": "testpass123"
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seed_transactions(auth_headers):
    """创建真实交易 + 0元垃圾通知"""
    # 真实交易（金额 > 0）
    client.post("/transactions", json={
        "amount": 25.5,
        "category": "餐饮",
        "account": "alipay",
        "transaction_type": "expense",
        "confidence": 1.0
    }, headers=auth_headers)
    client.post("/transactions", json={
        "amount": 100.0,
        "category": "购物",
        "account": "wechat_pay",
        "transaction_type": "expense",
        "confidence": 1.0
    }, headers=auth_headers)
    client.post("/transactions", json={
        "amount": 5000.0,
        "category": "金融",
        "account": "cmb",
        "transaction_type": "income",
        "confidence": 1.0
    }, headers=auth_headers)

    # 0元垃圾通知
    client.post("/transactions", json={
        "amount": 0,
        "category": "其他",
        "account": "other",
        "description": "快递包裹已签收",
        "transaction_type": "expense",
        "confidence": 0.3
    }, headers=auth_headers)
    client.post("/transactions", json={
        "amount": 0,
        "category": "其他",
        "account": "other",
        "description": "未接来电提醒",
        "transaction_type": "expense",
        "confidence": 0.2
    }, headers=auth_headers)


class TestHideNoise:
    """测试 hide_noise 过滤参数"""

    def test_without_hide_noise_returns_all(self, auth_headers, seed_transactions):
        """不传 hide_noise 时返回所有记录（含0元）"""
        resp = client.get("/transactions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 5  # 3 real + 2 noise

    def test_hide_noise_true_filters_zero_amount(self, auth_headers, seed_transactions):
        """hide_noise=true 时过滤掉0元记录"""
        resp = client.get("/transactions?hide_noise=true", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3  # only real transactions
        for tx in data:
            assert tx["amount"] > 0

    def test_hide_noise_false_returns_all(self, auth_headers, seed_transactions):
        """hide_noise=false 时返回所有记录"""
        resp = client.get("/transactions?hide_noise=false", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 5

    def test_hide_noise_with_other_filters(self, auth_headers, seed_transactions):
        """hide_noise 与其他过滤条件组合使用"""
        resp = client.get("/transactions?hide_noise=true&transaction_type=expense", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2  # 2 real expenses (25.5 + 100)
        for tx in data:
            assert tx["amount"] > 0
            assert tx["transaction_type"] == "expense"

    def test_hide_noise_with_account_filter(self, auth_headers, seed_transactions):
        """hide_noise + account 过滤"""
        resp = client.get("/transactions?hide_noise=true&account=alipay", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["amount"] == 25.5

    def test_unauthorized_still_blocked(self):
        """未认证仍然被拒绝"""
        resp = client.get("/transactions?hide_noise=true")
        assert resp.status_code == 401
