"""SilentBook 用户注册/登录 测试"""
import pytest
import sys
import os

# 确保可以 import app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


# ===== 测试数据库（SQLite in-memory）=====

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


# 启用外键约束（SQLite 默认关闭）
@event.listens_for(test_engine, "connect")
def enable_fk(dbapi_conn, conn_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    """每个测试前重建表"""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


# ===== 测试用例 =====


class TestRegister:
    """注册接口测试"""

    def test_register_with_email(self):
        """邮箱注册成功"""
        resp = client.post("/auth/register", json={
            "email": "test@example.com",
            "password": "pass1234",
            "nickname": "测试用户"
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "test@example.com"
        assert data["user"]["nickname"] == "测试用户"
        assert data["user"]["is_active"] is True

    def test_register_with_phone(self):
        """手机号注册成功"""
        resp = client.post("/auth/register", json={
            "phone": "13800138000",
            "password": "pass1234"
        })
        assert resp.status_code == 201
        assert resp.json()["user"]["phone"] == "13800138000"

    def test_register_email_and_phone(self):
        """同时填邮箱和手机号"""
        resp = client.post("/auth/register", json={
            "email": "both@example.com",
            "phone": "13900139000",
            "password": "pass1234"
        })
        assert resp.status_code == 201

    def test_register_no_contact(self):
        """邮箱和手机号都没填"""
        resp = client.post("/auth/register", json={
            "password": "pass1234"
        })
        assert resp.status_code == 422

    def test_register_short_password(self):
        """密码太短"""
        resp = client.post("/auth/register", json={
            "email": "short@example.com",
            "password": "123"
        })
        assert resp.status_code == 422

    def test_register_duplicate_email(self):
        """重复邮箱注册"""
        client.post("/auth/register", json={
            "email": "dup@example.com",
            "password": "pass1234"
        })
        resp = client.post("/auth/register", json={
            "email": "dup@example.com",
            "password": "pass5678"
        })
        assert resp.status_code == 409

    def test_register_duplicate_phone(self):
        """重复手机号注册"""
        client.post("/auth/register", json={
            "phone": "13800138000",
            "password": "pass1234"
        })
        resp = client.post("/auth/register", json={
            "phone": "13800138000",
            "password": "pass5678"
        })
        assert resp.status_code == 409

    def test_register_invalid_email(self):
        """邮箱格式错误"""
        resp = client.post("/auth/register", json={
            "email": "not-an-email",
            "password": "pass1234"
        })
        assert resp.status_code == 422

    def test_register_invalid_phone(self):
        """手机号格式错误"""
        resp = client.post("/auth/register", json={
            "phone": "12345",
            "password": "pass1234"
        })
        assert resp.status_code == 422


class TestLogin:
    """登录接口测试"""

    def setup_method(self):
        """先注册一个用户"""
        client.post("/auth/register", json={
            "email": "login@example.com",
            "phone": "13800138000",
            "password": "pass1234"
        })

    def test_login_with_email(self):
        """邮箱登录"""
        resp = client.post("/auth/login", json={
            "account": "login@example.com",
            "password": "pass1234"
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_with_phone(self):
        """手机号登录"""
        resp = client.post("/auth/login", json={
            "account": "13800138000",
            "password": "pass1234"
        })
        assert resp.status_code == 200

    def test_login_wrong_password(self):
        """密码错误"""
        resp = client.post("/auth/login", json={
            "account": "login@example.com",
            "password": "wrongpassword"
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self):
        """不存在的用户"""
        resp = client.post("/auth/login", json={
            "account": "nobody@example.com",
            "password": "pass1234"
        })
        assert resp.status_code == 401


class TestMe:
    """获取当前用户信息接口测试"""

    def setup_method(self):
        resp = client.post("/auth/register", json={
            "email": "me@example.com",
            "password": "pass1234"
        })
        self.token = resp.json()["access_token"]

    def test_get_me_with_token(self):
        """带 token 获取用户信息"""
        resp = client.get("/auth/me", headers={
            "Authorization": f"Bearer {self.token}"
        })
        assert resp.status_code == 200
        assert resp.json()["email"] == "me@example.com"

    def test_get_me_without_token(self):
        """不带 token 应返回 401"""
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_get_me_with_invalid_token(self):
        """无效 token 应返回 401"""
        resp = client.get("/auth/me", headers={
            "Authorization": "Bearer invalidtoken"
        })
        assert resp.status_code == 401
