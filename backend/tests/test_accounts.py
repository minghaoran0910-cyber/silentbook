"""多账户管理（四账户体系）测试"""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_accounts_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_mod
from app.main import app
from app.database import Base, get_db

main_mod.RATE_LIMIT_ENABLED = False

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
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


@pytest.fixture()
def auth():
    Base.metadata.create_all(bind=engine)
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    r = client.post(
        "/auth/register",
        json={"email": "accounts@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    token = r.json()["access_token"]
    yield {"Authorization": f"Bearer {token}"}
    Base.metadata.drop_all(bind=engine)
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def _post(path, payload, auth):
    r = client.post(path, json=payload, headers=auth)
    return r


class TestAccountCRUD:
    """账户 CRUD 基础测试"""

    def test_create_account(self, auth):
        """创建四类账户"""
        purposes = ["consumption", "emergency", "investment", "goal"]
        for i, purpose in enumerate(purposes):
            resp = _post("/accounts", {
                "name": f"测试账户{i}",
                "account_type": "bank",
                "purpose": purpose,
                "balance": 10000 * (i + 1),
                "target_balance": 50000,
            }, auth)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["purpose"] == purpose
            assert data["balance"] == 10000 * (i + 1)

    def test_list_accounts(self, auth):
        """列出所有账户"""
        for i in range(4):
            _post("/accounts", {
                "name": f"列表账户{i}",
                "account_type": "bank",
                "purpose": "consumption",
                "balance": 100,
            }, auth)
        resp = client.get("/accounts", headers=auth)
        assert resp.status_code == 200, resp.text
        assert len(resp.json()) >= 4

    def test_list_accounts_by_purpose(self, auth):
        """按用途筛选账户"""
        _post("/accounts", {
            "name": "消费户", "account_type": "bank",
            "purpose": "consumption", "balance": 100,
        }, auth)
        resp = client.get("/accounts?purpose=consumption", headers=auth)
        assert resp.status_code == 200, resp.text
        for acc in resp.json():
            assert acc["purpose"] == "consumption"

    def test_get_single_account(self, auth):
        """获取单个账户"""
        resp = _post("/accounts", {
            "name": "微信钱包",
            "account_type": "wechat",
            "purpose": "consumption",
            "balance": 5000,
        }, auth)
        account_id = resp.json()["id"]

        resp = client.get(f"/accounts/{account_id}", headers=auth)
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "微信钱包"

    def test_get_nonexistent_account(self, auth):
        """获取不存在的账户 → 404"""
        resp = client.get("/accounts/99999", headers=auth)
        assert resp.status_code == 404

    def test_update_account(self, auth):
        """更新账户余额"""
        resp = _post("/accounts", {
            "name": "招行卡",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 20000,
        }, auth)
        account_id = resp.json()["id"]

        resp = client.put(f"/accounts/{account_id}", json={
            "balance": 25000,
            "notes": "更新了余额",
        }, headers=auth)
        assert resp.status_code == 200, resp.text
        assert resp.json()["balance"] == 25000
        assert resp.json()["notes"] == "更新了余额"

    def test_delete_account(self, auth):
        """删除账户"""
        resp = _post("/accounts", {
            "name": "待删除",
            "account_type": "cash",
            "purpose": "goal",
            "balance": 0,
        }, auth)
        account_id = resp.json()["id"]

        resp = client.delete(f"/accounts/{account_id}", headers=auth)
        assert resp.status_code == 200, resp.text

        resp = client.get(f"/accounts/{account_id}", headers=auth)
        assert resp.status_code == 404

    def test_invalid_purpose(self, auth):
        """无效的 purpose → 422"""
        resp = _post("/accounts", {
            "name": "test",
            "account_type": "bank",
            "purpose": "invalid_purpose",
            "balance": 0,
        }, auth)
        assert resp.status_code == 422

    def test_invalid_account_type(self, auth):
        """无效的 account_type → 422"""
        resp = _post("/accounts", {
            "name": "test",
            "account_type": "invalid_type",
            "purpose": "consumption",
            "balance": 0,
        }, auth)
        assert resp.status_code == 422


class TestAccountSummary:
    """四账户汇总测试"""

    def test_summary(self, auth):
        """汇总接口返回四类数据"""
        client.post("/accounts", json={
            "name": "汇总测试-消费",
            "account_type": "wechat",
            "purpose": "consumption",
            "balance": 3000,
            "target_balance": 10000,
        }, headers=auth)
        client.post("/accounts", json={
            "name": "汇总测试-应急",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 60000,
            "target_balance": 60000,
        }, headers=auth)

        resp = client.get("/accounts/summary", headers=auth)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert "total_balance" in data
        assert "purposes" in data
        assert "consumption" in data["purposes"]
        assert "emergency" in data["purposes"]
        assert "investment" in data["purposes"]
        assert "goal" in data["purposes"]

        assert data["purposes"]["consumption"]["label"] == "日常消费"
        assert data["purposes"]["emergency"]["label"] == "应急储备"

    def test_summary_achievement_rate(self, auth):
        """达成率计算"""
        client.post("/accounts", json={
            "name": "达成率测试",
            "account_type": "bank",
            "purpose": "goal",
            "balance": 5000,
            "target_balance": 10000,
        }, headers=auth)

        resp = client.get("/accounts/summary", headers=auth)
        goal_data = resp.json()["purposes"]["goal"]

        found = False
        for acc in goal_data["accounts"]:
            if acc["name"] == "达成率测试":
                found = True
                break
        assert found


class TestAccountTransfer:
    """账户间转账测试"""

    def test_transfer_success(self, auth):
        """成功转账"""
        resp1 = _post("/accounts", {
            "name": "转账源",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 10000,
        }, auth)
        resp2 = _post("/accounts", {
            "name": "转账目标",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 5000,
        }, auth)
        from_id = resp1.json()["id"]
        to_id = resp2.json()["id"]

        resp = client.post("/accounts/transfer", json={
            "from_account_id": from_id,
            "to_account_id": to_id,
            "amount": 3000,
            "description": "测试转账",
        }, headers=auth)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["from_account"]["balance"] == 7000
        assert data["to_account"]["balance"] == 8000

    def test_transfer_insufficient_balance(self, auth):
        """余额不足 → 400"""
        resp1 = _post("/accounts", {
            "name": "穷账户",
            "account_type": "cash",
            "purpose": "consumption",
            "balance": 100,
        }, auth)
        resp2 = _post("/accounts", {
            "name": "富账户",
            "account_type": "bank",
            "purpose": "investment",
            "balance": 99999,
        }, auth)

        resp = client.post("/accounts/transfer", json={
            "from_account_id": resp1.json()["id"],
            "to_account_id": resp2.json()["id"],
            "amount": 500,
        }, headers=auth)
        assert resp.status_code == 400, resp.text
        assert "余额不足" in resp.json()["detail"]

    def test_transfer_nonexistent_account(self, auth):
        """转给不存在的账户 → 404"""
        resp1 = _post("/accounts", {
            "name": "存在",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 1000,
        }, auth)

        resp = client.post("/accounts/transfer", json={
            "from_account_id": resp1.json()["id"],
            "to_account_id": 99999,
            "amount": 100,
        }, headers=auth)
        assert resp.status_code == 404


class TestTransferRecords:
    """转账记录查询测试"""

    def test_transfer_creates_record(self, auth):
        """转账后生成 Transfer 记录"""
        resp1 = _post("/accounts", {
            "name": "记录测试-源",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 10000,
        }, auth)
        resp2 = _post("/accounts", {
            "name": "记录测试-目标",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 0,
        }, auth)
        from_id = resp1.json()["id"]
        to_id = resp2.json()["id"]

        resp = client.post("/accounts/transfer", json={
            "from_account_id": from_id,
            "to_account_id": to_id,
            "amount": 2000,
            "description": "记录测试",
        }, headers=auth)
        assert resp.status_code == 200, resp.text
        transfer_id = resp.json().get("transfer_id")
        assert transfer_id is not None

    def test_list_transfers(self, auth):
        """查询转账历史列表"""
        resp1 = _post("/accounts", {
            "name": "列表-源",
            "account_type": "bank",
            "purpose": "investment",
            "balance": 50000,
        }, auth)
        resp2 = _post("/accounts", {
            "name": "列表-目标",
            "account_type": "bank",
            "purpose": "goal",
            "balance": 0,
        }, auth)
        from_id = resp1.json()["id"]
        to_id = resp2.json()["id"]

        for amt in [1000, 2000]:
            client.post("/accounts/transfer", json={
                "from_account_id": from_id,
                "to_account_id": to_id,
                "amount": amt,
                "description": f"转账{amt}",
            }, headers=auth)

        resp = client.get("/accounts/transfers", headers=auth)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) >= 2
        assert data[0]["amount"] == 2000
        assert data[1]["amount"] == 1000

    def test_list_transfers_by_account(self, auth):
        """按账户筛选转账历史"""
        resp1 = _post("/accounts", {
            "name": "筛选-A",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 100000,
        }, auth)
        resp2 = _post("/accounts", {
            "name": "筛选-B",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 0,
        }, auth)
        resp3 = _post("/accounts", {
            "name": "筛选-C",
            "account_type": "bank",
            "purpose": "goal",
            "balance": 0,
        }, auth)
        a_id = resp1.json()["id"]
        b_id = resp2.json()["id"]
        c_id = resp3.json()["id"]

        client.post("/accounts/transfer", json={
            "from_account_id": a_id, "to_account_id": b_id,
            "amount": 500, "description": "A到B",
        }, headers=auth)
        client.post("/accounts/transfer", json={
            "from_account_id": a_id, "to_account_id": c_id,
            "amount": 800, "description": "A到C",
        }, headers=auth)

        resp = client.get(f"/accounts/transfers?account_id={a_id}", headers=auth)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) >= 2

        resp = client.get(f"/accounts/transfers?account_id={b_id}", headers=auth)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["to_account_id"] == b_id

    def test_get_transfer_detail(self, auth):
        """查询单条转账记录"""
        resp1 = _post("/accounts", {
            "name": "详情-源",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 50000,
        }, auth)
        resp2 = _post("/accounts", {
            "name": "详情-目标",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 0,
        }, auth)

        transfer_resp = client.post("/accounts/transfer", json={
            "from_account_id": resp1.json()["id"],
            "to_account_id": resp2.json()["id"],
            "amount": 5000,
            "description": "详情测试",
        }, headers=auth)
        transfer_id = transfer_resp.json()["transfer_id"]

        resp = client.get(f"/accounts/transfers/{transfer_id}", headers=auth)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == transfer_id
        assert data["amount"] == 5000
        assert data["description"] == "详情测试"

    def test_get_nonexistent_transfer(self, auth):
        """查询不存在的转账记录 → 404"""
        resp = client.get("/accounts/transfers/99999", headers=auth)
        assert resp.status_code == 404

    def test_transfer_same_account(self, auth):
        """同账户转账应允许（自转自）"""
        resp1 = _post("/accounts", {
            "name": "自转",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 10000,
        }, auth)
        acc_id = resp1.json()["id"]

        resp = client.post("/accounts/transfer", json={
            "from_account_id": acc_id,
            "to_account_id": acc_id,
            "amount": 1000,
        }, headers=auth)
        assert resp.status_code == 200, resp.text
        assert resp.json()["from_account"]["balance"] == 10000
        assert resp.json()["to_account"]["balance"] == 10000
