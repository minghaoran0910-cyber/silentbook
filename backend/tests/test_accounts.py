"""多账户管理（四账户体系）测试"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.main import app
from backend.app.database import Base, get_db
from backend.app.main import create_account, list_accounts, get_accounts_summary, transfer_between_accounts

# 使用 SQLite 内存数据库做测试
SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


class TestAccountCRUD:
    """账户 CRUD 基础测试"""

    def test_create_account(self):
        """创建四类账户"""
        purposes = ["consumption", "emergency", "investment", "goal"]
        for i, purpose in enumerate(purposes):
            resp = client.post("/accounts", json={
                "name": f"测试账户{i}",
                "account_type": "bank",
                "purpose": purpose,
                "balance": 10000 * (i + 1),
                "target_balance": 50000,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["purpose"] == purpose
            assert data["balance"] == 10000 * (i + 1)

    def test_list_accounts(self):
        """列出所有账户"""
        resp = client.get("/accounts")
        assert resp.status_code == 200
        assert len(resp.json()) >= 4

    def test_list_accounts_by_purpose(self):
        """按用途筛选账户"""
        resp = client.get("/accounts?purpose=consumption")
        assert resp.status_code == 200
        for acc in resp.json():
            assert acc["purpose"] == "consumption"

    def test_get_single_account(self):
        """获取单个账户"""
        # 先创建
        resp = client.post("/accounts", json={
            "name": "微信钱包",
            "account_type": "wechat",
            "purpose": "consumption",
            "balance": 5000,
        })
        account_id = resp.json()["id"]
        
        # 再获取
        resp = client.get(f"/accounts/{account_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "微信钱包"

    def test_get_nonexistent_account(self):
        """获取不存在的账户 → 404"""
        resp = client.get("/accounts/99999")
        assert resp.status_code == 404

    def test_update_account(self):
        """更新账户余额"""
        resp = client.post("/accounts", json={
            "name": "招行卡",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 20000,
        })
        account_id = resp.json()["id"]
        
        resp = client.put(f"/accounts/{account_id}", json={
            "balance": 25000,
            "notes": "更新了余额",
        })
        assert resp.status_code == 200
        assert resp.json()["balance"] == 25000
        assert resp.json()["notes"] == "更新了余额"

    def test_delete_account(self):
        """删除账户"""
        resp = client.post("/accounts", json={
            "name": "待删除",
            "account_type": "cash",
            "purpose": "goal",
            "balance": 0,
        })
        account_id = resp.json()["id"]
        
        resp = client.delete(f"/accounts/{account_id}")
        assert resp.status_code == 200
        
        # 确认已删除
        resp = client.get(f"/accounts/{account_id}")
        assert resp.status_code == 404

    def test_invalid_purpose(self):
        """无效的 purpose → 422"""
        resp = client.post("/accounts", json={
            "name": "test",
            "account_type": "bank",
            "purpose": "invalid_purpose",
            "balance": 0,
        })
        assert resp.status_code == 422

    def test_invalid_account_type(self):
        """无效的 account_type → 422"""
        resp = client.post("/accounts", json={
            "name": "test",
            "account_type": "invalid_type",
            "purpose": "consumption",
            "balance": 0,
        })
        assert resp.status_code == 422


class TestAccountSummary:
    """四账户汇总测试"""

    def test_summary(self):
        """汇总接口返回四类数据"""
        # 确保有数据
        client.post("/accounts", json={
            "name": "汇总测试-消费",
            "account_type": "wechat",
            "purpose": "consumption",
            "balance": 3000,
            "target_balance": 10000,
        })
        client.post("/accounts", json={
            "name": "汇总测试-应急",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 60000,
            "target_balance": 60000,
        })
        
        resp = client.get("/accounts/summary")
        assert resp.status_code == 200
        data = resp.json()
        
        assert "total_balance" in data
        assert "purposes" in data
        assert "consumption" in data["purposes"]
        assert "emergency" in data["purposes"]
        assert "investment" in data["purposes"]
        assert "goal" in data["purposes"]
        
        # 检查标签
        assert data["purposes"]["consumption"]["label"] == "日常消费"
        assert data["purposes"]["emergency"]["label"] == "应急储备"

    def test_summary_achievement_rate(self):
        """达成率计算"""
        client.post("/accounts", json={
            "name": "达成率测试",
            "account_type": "bank",
            "purpose": "goal",
            "balance": 5000,
            "target_balance": 10000,
        })
        
        resp = client.get("/accounts/summary")
        goal_data = resp.json()["purposes"]["goal"]
        
        # 找到我们刚创建的账户
        found = False
        for acc in goal_data["accounts"]:
            if acc["name"] == "达成率测试":
                found = True
                break
        assert found


class TestAccountTransfer:
    """账户间转账测试"""

    def test_transfer_success(self):
        """成功转账"""
        # 创建两个账户
        resp1 = client.post("/accounts", json={
            "name": "转账源",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 10000,
        })
        resp2 = client.post("/accounts", json={
            "name": "转账目标",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 5000,
        })
        from_id = resp1.json()["id"]
        to_id = resp2.json()["id"]
        
        # 转账
        resp = client.post("/accounts/transfer", json={
            "from_account_id": from_id,
            "to_account_id": to_id,
            "amount": 3000,
            "description": "测试转账",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["from_account"]["balance"] == 7000
        assert data["to_account"]["balance"] == 8000

    def test_transfer_insufficient_balance(self):
        """余额不足 → 400"""
        resp1 = client.post("/accounts", json={
            "name": "穷账户",
            "account_type": "cash",
            "purpose": "consumption",
            "balance": 100,
        })
        resp2 = client.post("/accounts", json={
            "name": "富账户",
            "account_type": "bank",
            "purpose": "investment",
            "balance": 99999,
        })
        
        resp = client.post("/accounts/transfer", json={
            "from_account_id": resp1.json()["id"],
            "to_account_id": resp2.json()["id"],
            "amount": 500,
        })
        assert resp.status_code == 400
        assert "余额不足" in resp.json()["detail"]

    def test_transfer_nonexistent_account(self):
        """转给不存在的账户 → 404"""
        resp1 = client.post("/accounts", json={
            "name": "存在",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 1000,
        })
        
        resp = client.post("/accounts/transfer", json={
            "from_account_id": resp1.json()["id"],
            "to_account_id": 99999,
            "amount": 100,
        })
        assert resp.status_code == 404


class TestTransferRecords:
    """转账记录查询测试"""

    def test_transfer_creates_record(self):
        """转账后生成 Transfer 记录"""
        resp1 = client.post("/accounts", json={
            "name": "记录测试-源",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 10000,
        })
        resp2 = client.post("/accounts", json={
            "name": "记录测试-目标",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 0,
        })
        from_id = resp1.json()["id"]
        to_id = resp2.json()["id"]
        
        # 转账
        resp = client.post("/accounts/transfer", json={
            "from_account_id": from_id,
            "to_account_id": to_id,
            "amount": 2000,
            "description": "记录测试",
        })
        assert resp.status_code == 200
        transfer_id = resp.json().get("transfer_id")
        assert transfer_id is not None

    def test_list_transfers(self):
        """查询转账历史列表"""
        # 创建账户并转账
        resp1 = client.post("/accounts", json={
            "name": "列表-源",
            "account_type": "bank",
            "purpose": "investment",
            "balance": 50000,
        })
        resp2 = client.post("/accounts", json={
            "name": "列表-目标",
            "account_type": "bank",
            "purpose": "goal",
            "balance": 0,
        })
        from_id = resp1.json()["id"]
        to_id = resp2.json()["id"]
        
        # 转两次
        for amt in [1000, 2000]:
            client.post("/accounts/transfer", json={
                "from_account_id": from_id,
                "to_account_id": to_id,
                "amount": amt,
                "description": f"转账{amt}",
            })
        
        # 查全部
        resp = client.get("/accounts/transfers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        # 按时间倒序
        assert data[0]["amount"] == 2000
        assert data[1]["amount"] == 1000

    def test_list_transfers_by_account(self):
        """按账户筛选转账历史"""
        resp1 = client.post("/accounts", json={
            "name": "筛选-A",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 100000,
        })
        resp2 = client.post("/accounts", json={
            "name": "筛选-B",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 0,
        })
        resp3 = client.post("/accounts", json={
            "name": "筛选-C",
            "account_type": "bank",
            "purpose": "goal",
            "balance": 0,
        })
        a_id = resp1.json()["id"]
        b_id = resp2.json()["id"]
        c_id = resp3.json()["id"]
        
        # A→B, A→C
        client.post("/accounts/transfer", json={
            "from_account_id": a_id, "to_account_id": b_id,
            "amount": 500, "description": "A到B",
        })
        client.post("/accounts/transfer", json={
            "from_account_id": a_id, "to_account_id": c_id,
            "amount": 800, "description": "A到C",
        })
        
        # 查 A 的转账记录（含转出和转入）
        resp = client.get(f"/accounts/transfers?account_id={a_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        
        # 查 B 的转账记录（只有转入）
        resp = client.get(f"/accounts/transfers?account_id={b_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["to_account_id"] == b_id

    def test_get_transfer_detail(self):
        """查询单条转账记录"""
        resp1 = client.post("/accounts", json={
            "name": "详情-源",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 50000,
        })
        resp2 = client.post("/accounts", json={
            "name": "详情-目标",
            "account_type": "bank",
            "purpose": "emergency",
            "balance": 0,
        })
        
        transfer_resp = client.post("/accounts/transfer", json={
            "from_account_id": resp1.json()["id"],
            "to_account_id": resp2.json()["id"],
            "amount": 5000,
            "description": "详情测试",
        })
        transfer_id = transfer_resp.json()["transfer_id"]
        
        resp = client.get(f"/accounts/transfers/{transfer_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == transfer_id
        assert data["amount"] == 5000
        assert data["description"] == "详情测试"

    def test_get_nonexistent_transfer(self):
        """查询不存在的转账记录 → 404"""
        resp = client.get("/accounts/transfers/99999")
        assert resp.status_code == 404

    def test_transfer_same_account(self):
        """同账户转账应允许（自转自）"""
        resp1 = client.post("/accounts", json={
            "name": "自转",
            "account_type": "bank",
            "purpose": "consumption",
            "balance": 10000,
        })
        acc_id = resp1.json()["id"]
        
        resp = client.post("/accounts/transfer", json={
            "from_account_id": acc_id,
            "to_account_id": acc_id,
            "amount": 1000,
        })
        # 同账户转账：余额不变，但记录生成
        assert resp.status_code == 200
        assert resp.json()["from_account"]["balance"] == 10000
        assert resp.json()["to_account"]["balance"] == 10000
