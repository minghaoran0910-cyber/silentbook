"""
SilentBook Backend Integration Tests

测试后端 API 的完整功能，包括：
- 交易 CRUD
- 手动记账
- 统计分析
- Agent 分析（mock）
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

# 测试数据库（内存 SQLite）
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 覆盖数据库依赖
def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

# 导入应用
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.main import app, get_db
from app.database import Base, Transaction, AnalysisResult

# 覆盖依赖
app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    """每个测试前重建数据库"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


class TestHealthCheck:
    def test_root(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "SilentBook API"
        assert "version" in data

    def test_health(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestTransactions:
    def test_create_transaction(self):
        """测试创建交易"""
        payload = {
            "amount": 38.5,
            "category": "餐饮",
            "account": "wechat_pay",
            "description": "星巴克消费",
            "transaction_type": "expense",
            "confidence": 0.9
        }
        response = client.post("/transactions", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["amount"] == 38.5
        assert data["category"] == "餐饮"
        assert data["account"] == "wechat_pay"
        assert data["transaction_type"] == "expense"
        assert "id" in data
        assert "parsed_at" in data

    def test_create_income_transaction(self):
        """测试创建收入交易"""
        payload = {
            "amount": 10000.0,
            "category": "工资",
            "account": "cmb",
            "description": "12月工资",
            "transaction_type": "income",
            "confidence": 1.0
        }
        response = client.post("/transactions", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["transaction_type"] == "income"
        assert data["amount"] == 10000.0

    def test_list_transactions(self):
        """测试获取交易列表"""
        # 先创建几条交易
        for i in range(3):
            client.post("/transactions", json={
                "amount": 10.0 * (i + 1),
                "category": "餐饮",
                "account": "wechat_pay",
                "transaction_type": "expense"
            })

        response = client.get("/transactions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # 验证按时间倒序
        assert data[0]["parsed_at"] >= data[1]["parsed_at"]

    def test_list_transactions_with_filters(self):
        """测试带筛选条件的交易列表"""
        # 创建不同账户的交易
        client.post("/transactions", json={
            "amount": 100.0,
            "category": "餐饮",
            "account": "wechat_pay",
            "transaction_type": "expense"
        })
        client.post("/transactions", json={
            "amount": 200.0,
            "category": "购物",
            "account": "alipay",
            "transaction_type": "expense"
        })
        client.post("/transactions", json={
            "amount": 5000.0,
            "category": "工资",
            "account": "cmb",
            "transaction_type": "income"
        })

        # 按账户筛选
        response = client.get("/transactions?account=wechat_pay")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["account"] == "wechat_pay"

        # 按分类筛选
        response = client.get("/transactions?category=购物")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["category"] == "购物"

        # 按类型筛选
        response = client.get("/transactions?transaction_type=income")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["transaction_type"] == "income"

    def test_get_single_transaction(self):
        """测试获取单条交易"""
        # 创建交易
        create_response = client.post("/transactions", json={
            "amount": 50.0,
            "category": "交通",
            "account": "alipay",
            "transaction_type": "expense"
        })
        tx_id = create_response.json()["id"]

        # 获取交易
        response = client.get(f"/transactions/{tx_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == tx_id
        assert data["amount"] == 50.0

    def test_get_nonexistent_transaction(self):
        """测试获取不存在的交易"""
        response = client.get("/transactions/99999")
        assert response.status_code == 404

    def test_update_transaction(self):
        """测试更新交易"""
        # 创建交易
        create_response = client.post("/transactions", json={
            "amount": 100.0,
            "category": "餐饮",
            "account": "wechat_pay",
            "description": "原始描述",
            "transaction_type": "expense"
        })
        tx_id = create_response.json()["id"]

        # 更新交易
        update_payload = {
            "amount": 120.0,
            "description": "更新后的描述"
        }
        response = client.put(f"/transactions/{tx_id}", json=update_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["amount"] == 120.0
        assert data["description"] == "更新后的描述"
        assert data["category"] == "餐饮"  # 未更新的字段保持不变

    def test_delete_transaction(self):
        """测试删除交易"""
        # 创建交易
        create_response = client.post("/transactions", json={
            "amount": 50.0,
            "category": "餐饮",
            "account": "wechat_pay",
            "transaction_type": "expense"
        })
        tx_id = create_response.json()["id"]

        # 删除交易
        response = client.delete(f"/transactions/{tx_id}")
        assert response.status_code == 200
        assert response.json()["message"] == "Transaction deleted"

        # 验证已删除
        response = client.get(f"/transactions/{tx_id}")
        assert response.status_code == 404

    def test_delete_all_transactions(self):
        """测试清空所有交易"""
        # 创建多条交易
        for i in range(5):
            client.post("/transactions", json={
                "amount": 10.0,
                "category": "餐饮",
                "account": "wechat_pay",
                "transaction_type": "expense"
            })

        # 清空（需要 confirm=true）
        response = client.delete("/transactions?confirm=true")
        assert response.status_code == 200
        assert "Deleted" in response.json()["message"]

        # 验证已清空
        response = client.get("/transactions")
        assert response.status_code == 200
        assert len(response.json()) == 0


class TestDashboardStats:
    def test_empty_stats(self):
        """测试空数据库的统计"""
        response = client.get("/stats/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["net_assets"] == 0
        assert data["monthly_income"] == 0
        assert data["monthly_expenses"] == 0
        assert data["transaction_count"] == 0

    def test_stats_with_transactions(self):
        """测试有交易数据的统计"""
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # 创建本月收入
        client.post("/transactions", json={
            "amount": 10000.0,
            "category": "工资",
            "account": "cmb",
            "transaction_type": "income"
        })

        # 创建本月支出
        client.post("/transactions", json={
            "amount": 3000.0,
            "category": "餐饮",
            "account": "wechat_pay",
            "transaction_type": "expense"
        })
        client.post("/transactions", json={
            "amount": 2000.0,
            "category": "购物",
            "account": "alipay",
            "transaction_type": "expense"
        })

        response = client.get("/stats/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["monthly_income"] == 10000.0
        assert data["monthly_expenses"] == 5000.0
        assert data["net_assets"] == 5000.0  # 10000 - 5000
        assert data["transaction_count"] == 3


class TestAnalysis:
    def test_latest_analysis_empty(self):
        """测试无分析结果时的返回"""
        response = client.get("/analysis/latest")
        assert response.status_code == 200
        data = response.json()
        assert "暂无分析" in data["consumption"]
        assert "暂无分析" in data["investment"]

    def test_analyze_endpoint(self):
        """测试分析接口（会调用 mock agent）"""
        # 先创建一些交易
        for i in range(3):
            client.post("/transactions", json={
                "amount": 100.0 * (i + 1),
                "category": "餐饮",
                "account": "wechat_pay",
                "transaction_type": "expense"
            })

        # 调用分析（会失败，因为 agent 服务不存在，但应该返回默认值）
        response = client.post("/analyze")
        assert response.status_code == 200
        data = response.json()
        # 即使 agent 不可用，也应该返回结构
        assert "consumption" in data
        assert "investment" in data
        assert "suggestion" in data


class TestManualEntry:
    """手动记账完整流程测试"""

    def test_manual_entry_workflow(self):
        """测试手动记账完整流程"""
        # 1. 创建交易
        payload = {
            "amount": 88.0,
            "category": "餐饮",
            "account": "wechat_pay",
            "description": "朋友聚餐",
            "transaction_type": "expense",
            "confidence": 1.0  # 手动记账置信度为 1.0
        }
        response = client.post("/transactions", json=payload)
        assert response.status_code == 200
        tx = response.json()
        assert tx["amount"] == 88.0
        assert tx["confidence"] == 1.0

        # 2. 验证交易在列表中
        response = client.get("/transactions")
        assert response.status_code == 200
        transactions = response.json()
        assert len(transactions) == 1
        assert transactions[0]["description"] == "朋友聚餐"

        # 3. 验证统计更新
        response = client.get("/stats/dashboard")
        assert response.status_code == 200
        stats = response.json()
        assert stats["monthly_expenses"] == 88.0
        assert stats["transaction_count"] == 1

        # 4. 修改交易
        response = client.put(f"/transactions/{tx['id']}", json={
            "amount": 100.0,
            "description": "朋友聚餐（AA）"
        })
        assert response.status_code == 200
        updated = response.json()
        assert updated["amount"] == 100.0
        assert updated["description"] == "朋友聚餐（AA）"

        # 5. 验证统计再次更新
        response = client.get("/stats/dashboard")
        assert response.status_code == 200
        stats = response.json()
        assert stats["monthly_expenses"] == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
