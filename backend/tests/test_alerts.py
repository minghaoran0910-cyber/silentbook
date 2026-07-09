"""V2-007 五级预警阈值 - 测试套件"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, Setting, Transaction
from app.main import app, get_alert_level, ALERT_LEVELS
from datetime import datetime

# SQLite 内存数据库
SQLALCHEMY_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_expense(db, category, amount):
    """辅助：添加一条支出"""
    db.add(Transaction(
        amount=amount, category=category, account="微信",
        transaction_type="expense", parsed_at=datetime.utcnow()
    ))
    db.commit()


# ===== get_alert_level 单元测试 =====

class TestGetAlertLevel:
    """测试 get_alert_level 函数的边界值"""

    def test_zero_usage_is_safe(self):
        result = get_alert_level(0.0)
        assert result["level"] == 1
        assert result["name"] == "安全"

    def test_below_50_percent_is_safe(self):
        result = get_alert_level(0.49)
        assert result["level"] == 1

    def test_exactly_50_percent_is_normal(self):
        result = get_alert_level(0.5)
        assert result["level"] == 2
        assert result["name"] == "正常"

    def test_below_80_percent_is_normal(self):
        result = get_alert_level(0.79)
        assert result["level"] == 2

    def test_exactly_80_percent_is_notice(self):
        result = get_alert_level(0.8)
        assert result["level"] == 3
        assert result["name"] == "提醒"

    def test_below_100_percent_is_notice(self):
        result = get_alert_level(0.99)
        assert result["level"] == 3

    def test_exactly_100_percent_is_over(self):
        result = get_alert_level(1.0)
        assert result["level"] == 4
        assert result["name"] == "超支"

    def test_below_120_percent_is_over(self):
        result = get_alert_level(1.19)
        assert result["level"] == 4

    def test_exactly_120_percent_is_critical(self):
        result = get_alert_level(1.2)
        assert result["level"] == 5
        assert result["name"] == "严重超支"

    def test_way_over_is_critical(self):
        result = get_alert_level(2.5)
        assert result["level"] == 5

    def test_custom_thresholds(self):
        """自定义阈值"""
        custom = [0.3, 0.6, 0.9, 1.5]
        assert get_alert_level(0.25, custom)["level"] == 1
        assert get_alert_level(0.3, custom)["level"] == 2
        assert get_alert_level(0.6, custom)["level"] == 3
        assert get_alert_level(0.9, custom)["level"] == 4
        assert get_alert_level(1.5, custom)["level"] == 5

    def test_invalid_custom_thresholds_falls_back(self):
        """无效自定义阈值回退到默认"""
        result = get_alert_level(0.5, [0.1])  # 长度不对
        assert result["level"] == 2  # 用默认阈值

    def test_all_levels_have_required_fields(self):
        for level in ALERT_LEVELS:
            assert "level" in level
            assert "name" in level
            assert "color" in level
            assert "max" in level


# ===== GET /budgets/alerts 端点 =====

class TestBudgetAlertsEndpoint:
    """测试 /budgets/alerts 端点"""

    def test_empty_budgets(self, client):
        """无预算时返回空"""
        resp = client.get("/budgets/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alerts"] == []
        assert data["summary"]["safe"] == 0
        assert data["summary"]["critical"] == 0

    def test_safe_level(self, client, db_session):
        """使用率 < 50% → 安全"""
        client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 1000, "level": "L1"
        })
        add_expense(db_session, "餐饮", 400)  # 40%

        resp = client.get("/budgets/alerts")
        data = resp.json()
        alert = data["alerts"][0]
        assert alert["alert_level"] == 1
        assert alert["alert_name"] == "安全"
        assert alert["alert_color"] == "green"
        assert data["summary"]["safe"] == 1

    def test_normal_level(self, client, db_session):
        """50% ≤ 使用率 < 80% → 正常"""
        client.post("/budgets", json={
            "category": "健身", "monthly_limit": 1000, "level": "L2"
        })
        add_expense(db_session, "健身", 600)  # 60%

        resp = client.get("/budgets/alerts")
        alert = resp.json()["alerts"][0]
        assert alert["alert_level"] == 2
        assert alert["alert_name"] == "正常"

    def test_notice_level(self, client, db_session):
        """80% ≤ 使用率 < 100% → 提醒"""
        client.post("/budgets", json={
            "category": "咖啡", "monthly_limit": 500, "level": "L2"
        })
        add_expense(db_session, "咖啡", 450)  # 90%

        resp = client.get("/budgets/alerts")
        alert = resp.json()["alerts"][0]
        assert alert["alert_level"] == 3
        assert alert["alert_name"] == "提醒"

    def test_over_level(self, client, db_session):
        """100% ≤ 使用率 < 120% → 超支"""
        client.post("/budgets", json={
            "category": "游戏", "monthly_limit": 100, "level": "L3"
        })
        add_expense(db_session, "游戏", 110)  # 110%

        resp = client.get("/budgets/alerts")
        alert = resp.json()["alerts"][0]
        assert alert["alert_level"] == 4
        assert alert["alert_name"] == "超支"

    def test_critical_level(self, client, db_session):
        """使用率 ≥ 120% → 严重超支"""
        client.post("/budgets", json={
            "category": "购物", "monthly_limit": 100, "level": "L3"
        })
        add_expense(db_session, "购物", 150)  # 150%

        resp = client.get("/budgets/alerts")
        alert = resp.json()["alerts"][0]
        assert alert["alert_level"] == 5
        assert alert["alert_name"] == "严重超支"
        assert resp.json()["summary"]["critical"] == 1

    def test_summary_counts_multiple_budgets(self, client, db_session):
        """多个预算的汇总计数"""
        client.post("/budgets", json={"category": "房租", "monthly_limit": 5000, "level": "L1"})
        client.post("/budgets", json={"category": "健身", "monthly_limit": 1000, "level": "L2"})
        client.post("/budgets", json={"category": "游戏", "monthly_limit": 100, "level": "L3"})
        client.post("/budgets", json={"category": "购物", "monthly_limit": 100, "level": "L3"})

        add_expense(db_session, "房租", 1000)    # 20% → 安全
        add_expense(db_session, "健身", 600)     # 60% → 正常
        add_expense(db_session, "游戏", 90)      # 90% → 提醒
        add_expense(db_session, "购物", 150)     # 150% → 严重超支

        resp = client.get("/budgets/alerts")
        data = resp.json()
        assert data["summary"]["safe"] == 1
        assert data["summary"]["normal"] == 1
        assert data["summary"]["notice"] == 1
        assert data["summary"]["over"] == 0
        assert data["summary"]["critical"] == 1
        assert len(data["alerts"]) == 4

    def test_alert_includes_budget_level(self, client):
        """alerts 返回预算级别字段"""
        client.post("/budgets", json={
            "category": "房租", "monthly_limit": 5000, "level": "L1"
        })
        resp = client.get("/budgets/alerts")
        alert = resp.json()["alerts"][0]
        assert alert["level"] == "L1"

    def test_custom_thresholds_in_alerts(self, client, db_session):
        """自定义阈值在 alerts 中生效"""
        client.post("/budgets", json={
            "category": "餐饮",
            "monthly_limit": 1000,
            "level": "L1",
            "alert_thresholds": [0.3, 0.6, 0.9, 1.5]
        })
        add_expense(db_session, "餐饮", 350)  # 35% → 超过自定义 30% → Level 2

        resp = client.get("/budgets/alerts")
        alert = resp.json()["alerts"][0]
        assert alert["alert_level"] == 2  # 正常（自定义阈值下）


# ===== GET /budgets 集成测试 =====

class TestBudgetsWithAlertLevel:
    """测试 GET /budgets 返回 alert_level 字段"""

    def test_budgets_include_alert_fields(self, client, db_session):
        """GET /budgets 包含预警字段"""
        client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 1000, "level": "L1"
        })
        add_expense(db_session, "餐饮", 850)  # 85% → 提醒

        resp = client.get("/budgets")
        budget = resp.json()[0]
        assert budget["alert_level"] == 3
        assert budget["alert_name"] == "提醒"
        assert budget["alert_color"] == "yellow"
        # 旧字段仍在
        assert "alert" in budget
        assert "alert_threshold" in budget

    def test_budgets_with_no_spending_is_safe(self, client):
        """无支出时为安全"""
        client.post("/budgets", json={
            "category": "娱乐", "monthly_limit": 500, "level": "L3"
        })
        resp = client.get("/budgets")
        budget = resp.json()[0]
        assert budget["alert_level"] == 1
        assert budget["alert_name"] == "安全"


# ===== GET /budgets/levels 集成测试 =====

class TestBudgetLevelsWithAlert:
    """测试 GET /budgets/levels items 包含 alert_level"""

    def test_levels_items_include_alert_fields(self, client, db_session):
        client.post("/budgets", json={
            "category": "餐饮", "monthly_limit": 1000, "level": "L1"
        })
        add_expense(db_session, "餐饮", 850)  # 85% → 提醒

        resp = client.get("/budgets/levels")
        item = resp.json()["levels"]["L1"]["items"][0]
        assert item["alert_level"] == 3
        assert item["alert_name"] == "提醒"
        assert item["alert_color"] == "yellow"


# ===== 向后兼容 =====

class TestBackwardCompat:
    """旧数据兼容"""

    def test_old_budget_without_alert_thresholds(self, client, db_session):
        """旧预算数据（无 alert_thresholds 字段）使用默认阈值"""
        db_session.add(Setting(key="budgets", value=json.dumps([
            {"category": "房租", "monthly_limit": 5000, "alert_threshold": 0.8},
        ])))
        db_session.commit()
        add_expense(db_session, "房租", 4300)  # 86% → 提醒（默认阈值）

        resp = client.get("/budgets/alerts")
        alert = resp.json()["alerts"][0]
        assert alert["alert_level"] == 3
        assert alert["alert_name"] == "提醒"

    def test_create_with_custom_thresholds_persists(self, client):
        """创建带自定义阈值的预算，阈值被持久化"""
        client.post("/budgets", json={
            "category": "餐饮",
            "monthly_limit": 3000,
            "level": "L1",
            "alert_thresholds": [0.3, 0.6, 0.9, 1.5]
        })
        # 再查
        resp = client.get("/budgets")
        budget = resp.json()[0]
        assert budget.get("alert_thresholds") == [0.3, 0.6, 0.9, 1.5]

    def test_update_keeps_alert_thresholds(self, client):
        """更新预算时保留 alert_thresholds"""
        client.post("/budgets", json={
            "category": "餐饮",
            "monthly_limit": 3000,
            "level": "L1",
            "alert_thresholds": [0.3, 0.6, 0.9, 1.5]
        })
        # 更新 monthly_limit
        client.post("/budgets", json={
            "category": "餐饮",
            "monthly_limit": 3500,
            "level": "L1",
            "alert_thresholds": [0.3, 0.6, 0.9, 1.5]
        })
        resp = client.get("/budgets")
        budget = resp.json()[0]
        assert budget["monthly_limit"] == 3500
        assert budget["alert_thresholds"] == [0.3, 0.6, 0.9, 1.5]
