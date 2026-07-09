"""V2-006 三级分类预算 - 测试套件"""
import pytest
import sys
import os

# 确保能导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, Setting, Transaction
from app.main import app, BudgetCreate

# 使用 SQLite 内存数据库
SQLALCHEMY_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """每个测试独立的数据库 session"""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """带数据库替换的测试客户端"""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ===== 基础预算 CRUD =====

class TestBudgetCRUD:
    """测试预算基础增删改查（兼容 level 字段）"""

    def test_create_budget_with_level(self, client):
        """创建带级别字段的预算"""
        resp = client.post("/budgets", json={
            "category": "餐饮",
            "monthly_limit": 3000,
            "alert_threshold": 0.8,
            "level": "L1"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "budgets" in data
        budget = data["budgets"][0]
        assert budget["category"] == "餐饮"
        assert budget["level"] == "L1"

    def test_create_budget_default_level(self, client):
        """不指定 level 时默认 L2"""
        resp = client.post("/budgets", json={
            "category": "健身",
            "monthly_limit": 500,
        })
        assert resp.status_code == 200
        budget = resp.json()["budgets"][0]
        assert budget["level"] == "L2"

    def test_create_budget_invalid_level(self, client):
        """无效 level 应被拒绝"""
        resp = client.post("/budgets", json={
            "category": "娱乐",
            "monthly_limit": 200,
            "level": "L4"
        })
        assert resp.status_code == 422

    def test_get_budgets_returns_level(self, client):
        """GET /budgets 返回 level 字段"""
        client.post("/budgets", json={
            "category": "房租", "monthly_limit": 5000, "level": "L1"
        })
        client.post("/budgets", json={
            "category": "咖啡", "monthly_limit": 300, "level": "L2"
        })
        client.post("/budgets", json={
            "category": "游戏", "monthly_limit": 100, "level": "L3"
        })

        resp = client.get("/budgets")
        assert resp.status_code == 200
        budgets = resp.json()
        assert len(budgets) == 3
        levels = {b["category"]: b["level"] for b in budgets}
        assert levels["房租"] == "L1"
        assert levels["咖啡"] == "L2"
        assert levels["游戏"] == "L3"

    def test_update_existing_budget_keeps_level(self, client):
        """更新已有预算时保留 level"""
        client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 3000, "level": "L1"
        })
        # 更新
        client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 3500, "level": "L1"
        })
        resp = client.get("/budgets")
        budget = [b for b in resp.json() if b["category"] == "餐饮"][0]
        assert budget["monthly_limit"] == 3500
        assert budget["level"] == "L1"

    def test_delete_budget(self, client):
        """删除预算"""
        client.post("/budgets", json={
            "category": "娱乐", "monthly_limit": 200, "level": "L3"
        })
        resp = client.delete("/budgets/娱乐")
        assert resp.status_code == 200
        resp2 = client.get("/budgets")
        assert len(resp2.json()) == 0


# ===== 三级分类汇总 =====

class TestBudgetLevels:
    """测试 /budgets/levels 端点"""

    def test_empty_budgets_returns_zero(self, client):
        """无预算时返回空结构"""
        resp = client.get("/budgets/levels")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_budget"] == 0
        assert data["total_spent"] == 0
        assert "L1" in data["levels"]
        assert "L2" in data["levels"]
        assert "L3" in data["levels"]
        assert data["levels"]["L1"]["label"] == "必要支出"
        assert data["levels"]["L2"]["label"] == "改善支出"
        assert data["levels"]["L3"]["label"] == "非必要支出"

    def test_levels_with_budgets_only(self, client):
        """只有预算无支出时"""
        client.post("/budgets", json={
            "category": "房租", "monthly_limit": 5000, "level": "L1"
        })
        client.post("/budgets", json={
            "category": "健身", "monthly_limit": 500, "level": "L2"
        })
        client.post("/budgets", json={
            "category": "游戏", "monthly_limit": 100, "level": "L3"
        })

        resp = client.get("/budgets/levels")
        data = resp.json()
        assert data["total_budget"] == 5600
        assert data["levels"]["L1"]["budget_total"] == 5000
        assert data["levels"]["L2"]["budget_total"] == 500
        assert data["levels"]["L3"]["budget_total"] == 100

    def test_levels_with_spending(self, client, db_session):
        """有预算+有支出的完整场景"""
        # 创建预算
        client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 3000, "level": "L1"
        })
        client.post("/budgets", json={
            "category": "健身", "monthly_limit": 500, "level": "L2"
        })
        client.post("/budgets", json={
            "category": "游戏", "monthly_limit": 100, "level": "L3"
        })

        # 添加支出
        from datetime import datetime
        txs = [
            Transaction(amount=200, category="餐饮", account="微信",
                         transaction_type="expense", parsed_at=datetime.utcnow()),
            Transaction(amount=50, category="餐饮", account="微信",
                         transaction_type="expense", parsed_at=datetime.utcnow()),
            Transaction(amount=300, category="健身", account="支付宝",
                         transaction_type="expense", parsed_at=datetime.utcnow()),
            Transaction(amount=80, category="游戏", account="微信",
                         transaction_type="expense", parsed_at=datetime.utcnow()),
        ]
        for tx in txs:
            db_session.add(tx)
        db_session.commit()

        resp = client.get("/budgets/levels")
        data = resp.json()

        # L1: 餐饮 250/3000
        assert data["levels"]["L1"]["spent_total"] == 250
        assert data["levels"]["L1"]["budget_total"] == 3000
        # L2: 健身 300/500
        assert data["levels"]["L2"]["spent_total"] == 300
        assert data["levels"]["L2"]["budget_total"] == 500
        # L3: 游戏 80/100
        assert data["levels"]["L3"]["spent_total"] == 80
        assert data["levels"]["L3"]["budget_total"] == 100

    def test_unbudgeted_spending_by_default_mapping(self, client, db_session):
        """未设预算但属于该级别的支出也应统计"""
        # 只设一个预算
        client.post("/budgets", json={
            "category": "房租", "monthly_limit": 5000, "level": "L1"
        })

        # 添加未设预算的支出（餐饮默认 L1）
        from datetime import datetime
        tx = Transaction(amount=100, category="餐饮", account="微信",
                         transaction_type="expense", parsed_at=datetime.utcnow())
        db_session.add(tx)
        db_session.commit()

        resp = client.get("/budgets/levels")
        data = resp.json()
        # L1 应包含 房租(预算) + 餐饮(默认映射)
        assert data["levels"]["L1"]["spent_total"] == 100
        assert data["levels"]["L1"]["unbudgeted_spent"] == 100

    def test_over_budget_alert(self, client, db_session):
        """超支预警"""
        client.post("/budgets", json={
            "category": "游戏", "monthly_limit": 100,
            "alert_threshold": 0.8, "level": "L3"
        })

        from datetime import datetime
        tx = Transaction(amount=90, category="游戏", account="微信",
                         transaction_type="expense", parsed_at=datetime.utcnow())
        db_session.add(tx)
        db_session.commit()

        resp = client.get("/budgets/levels")
        data = resp.json()
        item = data["levels"]["L3"]["items"][0]
        assert item["alert"] is True
        assert item["usage_rate"] == 90.0

    def test_level_compressibility_labels(self, client):
        """验证可压缩性标签"""
        resp = client.get("/budgets/levels")
        data = resp.json()
        assert data["levels"]["L1"]["compressibility"] == "<10%"
        assert data["levels"]["L2"]["compressibility"] == "30-50%"
        assert data["levels"]["L3"]["compressibility"] == "80-100%"


# ===== 默认分类映射 =====

class TestDefaultCategoryMapping:
    """测试默认分类→级别映射"""

    def test_known_categories_mapped(self, client, db_session):
        """已知分类自动归入正确级别"""
        from datetime import datetime
        txs = [
            Transaction(amount=100, category="房租", account="",
                         transaction_type="expense", parsed_at=datetime.utcnow()),
            Transaction(amount=200, category="学习", account="",
                         transaction_type="expense", parsed_at=datetime.utcnow()),
            Transaction(amount=50, category="游戏", account="",
                         transaction_type="expense", parsed_at=datetime.utcnow()),
        ]
        for tx in txs:
            db_session.add(tx)
        db_session.commit()

        resp = client.get("/budgets/levels")
        data = resp.json()
        # 房租 → L1
        assert data["levels"]["L1"]["unbudgeted_spent"] == 100
        # 学习 → L2
        assert data["levels"]["L2"]["unbudgeted_spent"] == 200
        # 游戏 → L3
        assert data["levels"]["L3"]["unbudgeted_spent"] == 50

    def test_unknown_category_defaults_l2(self, client, db_session):
        """未知分类默认归入 L2"""
        from datetime import datetime
        tx = Transaction(amount=77, category="奇葩分类", account="",
                         transaction_type="expense", parsed_at=datetime.utcnow())
        db_session.add(tx)
        db_session.commit()

        resp = client.get("/budgets/levels")
        data = resp.json()
        assert data["levels"]["L2"]["unbudgeted_spent"] == 77


# ===== 向后兼容 =====

class TestBackwardCompat:
    """测试旧数据（无 level 字段）的兼容性"""

    def test_old_budget_data_without_level(self, client, db_session):
        """旧预算数据没有 level 字段时自动补全"""
        import json
        # 直接写入旧格式数据
        db_session.add(Setting(key="budgets", value=json.dumps([
            {"category": "房租", "monthly_limit": 5000, "alert_threshold": 0.8},
            {"category": "游戏", "monthly_limit": 200, "alert_threshold": 0.8},
        ])))
        db_session.commit()

        resp = client.get("/budgets/levels")
        assert resp.status_code == 200
        data = resp.json()
        # 房租 → 默认映射 L1
        assert data["levels"]["L1"]["budget_total"] == 5000
        # 游戏 → 默认映射 L3
        assert data["levels"]["L3"]["budget_total"] == 200

    def test_existing_endpoints_work(self, client):
        """已有端点不受影响"""
        resp = client.get("/budgets")
        assert resp.status_code == 200
        assert resp.json() == []

        # 创建
        resp = client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 2000
        })
        assert resp.status_code == 200

        # 查询
        resp = client.get("/budgets")
        assert resp.status_code == 200
        budgets = resp.json()
        assert len(budgets) == 1
        assert budgets[0]["category"] == "餐饮"
        assert budgets[0]["level"] == "L2"  # 默认

        # 删除
        resp = client.delete("/budgets/餐饮")
        assert resp.status_code == 200
