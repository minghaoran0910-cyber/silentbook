"""V2-021 预算执行报表测试"""
import pytest
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import get_db, Base, Transaction, Setting

SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _add_tx(db, category, amount, tx_type="expense", days_ago=0):
    tx = Transaction(
        category=category,
        amount=amount,
        account="default",
        transaction_type=tx_type,
        parsed_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.add(tx)
    db.commit()


def _set_budgets(db, budgets):
    raw = Setting(key="budgets", value=json.dumps(budgets))
    db.merge(raw)
    db.commit()


class TestBudgetExecutionReport:
    """预算执行报表核心测试"""

    def test_no_budgets(self):
        """无预算时返回空结果和提示信息"""
        resp = client.get("/reports/budget-execution")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_budget"] == 0
        assert data["summary"]["total_spent"] == 0
        assert "message" in data

    def test_basic_execution(self):
        """基本预算执行：预算1000，花了600"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 1000, "level": "L1"}])
        _add_tx(db, "餐饮", 600)
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        assert data["summary"]["total_budget"] == 1000
        assert data["summary"]["total_spent"] == 600
        assert data["summary"]["remaining"] == 400
        assert data["summary"]["execution_rate"] == 60.0
        assert len(data["by_category"]) == 1
        assert data["by_category"][0]["category"] == "餐饮"
        assert data["by_category"][0]["usage_rate"] == 60.0
        assert data["by_category"][0]["deviation"] == -400

    def test_over_budget(self):
        """超支场景：预算500，花了800"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "娱乐", "monthly_limit": 500, "level": "L3"}])
        _add_tx(db, "娱乐", 800)
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        assert data["summary"]["execution_rate"] == 160.0
        assert data["summary"]["over_budget_count"] == 1
        cat = data["by_category"][0]
        assert cat["deviation"] == 300
        assert cat["deviation_rate"] == 60.0
        assert cat["alert_level"] >= 4  # 超支级别

    def test_multi_category(self):
        """多分类预算"""
        db = TestingSessionLocal()
        _set_budgets(db, [
            {"category": "餐饮", "monthly_limit": 2000, "level": "L1"},
            {"category": "交通", "monthly_limit": 500, "level": "L1"},
            {"category": "健身", "monthly_limit": 300, "level": "L2"},
        ])
        _add_tx(db, "餐饮", 1500)
        _add_tx(db, "交通", 600)  # 超支
        _add_tx(db, "健身", 100)
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        assert data["summary"]["total_budget"] == 2800
        assert data["summary"]["total_spent"] == 2200
        assert data["summary"]["over_budget_count"] == 1  # 交通超支
        assert len(data["by_category"]) == 3

    def test_by_level_summary(self):
        """按级别汇总"""
        db = TestingSessionLocal()
        _set_budgets(db, [
            {"category": "餐饮", "monthly_limit": 2000, "level": "L1"},
            {"category": "交通", "monthly_limit": 500, "level": "L1"},
            {"category": "健身", "monthly_limit": 300, "level": "L2"},
            {"category": "娱乐", "monthly_limit": 200, "level": "L3"},
        ])
        _add_tx(db, "餐饮", 1500)
        _add_tx(db, "交通", 400)
        _add_tx(db, "健身", 200)
        _add_tx(db, "娱乐", 250)  # 超支
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        levels = data["by_level"]
        assert "L1" in levels
        assert "L2" in levels
        assert "L3" in levels
        assert levels["L1"]["budget_limit"] == 2500
        assert levels["L1"]["actual_spent"] == 1900
        assert levels["L3"]["usage_rate"] == 125.0  # 250/200

    def test_unbudgeted_categories(self):
        """未设预算但有支出的分类"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 1000, "level": "L1"}])
        _add_tx(db, "餐饮", 500)
        _add_tx(db, "咖啡", 200)  # 没设预算
        _add_tx(db, "水果", 150)  # 没设预算
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        assert len(data["unbudgeted_categories"]) == 2
        cats = [u["category"] for u in data["unbudgeted_categories"]]
        assert "咖啡" in cats
        assert "水果" in cats

    def test_alerts(self):
        """预警列表"""
        db = TestingSessionLocal()
        _set_budgets(db, [
            {"category": "餐饮", "monthly_limit": 1000, "level": "L1"},
            {"category": "娱乐", "monthly_limit": 300, "level": "L3"},
        ])
        _add_tx(db, "餐饮", 500)  # 50% - 安全
        _add_tx(db, "娱乐", 400)  # 133% - 超支
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        # 娱乐应该出现在 alerts 中
        assert len(data["alerts"]) >= 1
        alert_cats = [a["category"] for a in data["alerts"]]
        assert "娱乐" in alert_cats
        # 餐饮 50% 不应在告警中（alert_level < 3）
        assert "餐饮" not in alert_cats

    def test_trend(self):
        """趋势分析"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 1000, "level": "L1"}])
        # 当月
        _add_tx(db, "餐饮", 800, days_ago=0)
        # 30天前（上个月）
        _add_tx(db, "餐饮", 600, days_ago=30)
        db.close()

        resp = client.get("/reports/budget-execution?months=2")
        data = resp.json()
        assert len(data["trend"]) == 2
        # 趋势按时间顺序排列
        assert data["trend"][0]["period"] <= data["trend"][1]["period"]

    def test_specific_month(self):
        """指定年月查询"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 1000, "level": "L1"}])
        # 添加2月份的交易
        tx = Transaction(
            category="餐饮", amount=700, account="default",
            transaction_type="expense",
            parsed_at=datetime(2026, 2, 15),
        )
        db.add(tx)
        db.commit()
        db.close()

        resp = client.get("/reports/budget-execution?year=2026&month=2")
        data = resp.json()
        assert data["year"] == 2026
        assert data["month"] == 2
        assert data["summary"]["total_spent"] == 700

    def test_daily_budget_calculation(self):
        """日均预算和日均实际计算"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 3000, "level": "L1"}])
        _add_tx(db, "餐饮", 1500)
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        summary = data["summary"]
        assert summary["daily_budget"] > 0
        assert summary["daily_actual"] > 0
        assert summary["days_in_month"] > 0
        assert summary["days_elapsed"] > 0

    def test_projected_usage(self):
        """预测使用率"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 1000, "level": "L1"}])
        _add_tx(db, "餐饮", 500)
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        # 预测使用率应该基于日均消费外推
        projected = data["summary"]["projected_usage"]
        assert projected > 0

    def test_empty_transactions(self):
        """有预算但无交易"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 1000, "level": "L1"}])
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        assert data["summary"]["total_spent"] == 0
        assert data["summary"]["execution_rate"] == 0
        assert data["by_category"][0]["actual_spent"] == 0
        assert data["by_category"][0]["deviation"] == -1000

    def test_income_not_counted(self):
        """收入不计入预算执行"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 1000, "level": "L1"}])
        _add_tx(db, "餐饮", 500, tx_type="expense")
        _add_tx(db, "餐饮", 2000, tx_type="income")  # 收入不影响
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        assert data["summary"]["total_spent"] == 500

    def test_sort_by_deviation(self):
        """分类按偏差率降序排列"""
        db = TestingSessionLocal()
        _set_budgets(db, [
            {"category": "餐饮", "monthly_limit": 1000, "level": "L1"},
            {"category": "娱乐", "monthly_limit": 500, "level": "L3"},
            {"category": "交通", "monthly_limit": 800, "level": "L1"},
        ])
        _add_tx(db, "餐饮", 600)   # -40% 偏差
        _add_tx(db, "娱乐", 800)   # +60% 偏差
        _add_tx(db, "交通", 400)   # -50% 偏差
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        cats = data["by_category"]
        # 第一个应该是偏差率最高的（娱乐 +60%）
        assert cats[0]["category"] == "娱乐"
        assert cats[0]["deviation_rate"] > 0

    def test_level_auto_fill(self):
        """旧预算数据无level字段时自动补全"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 1000}])  # 无 level
        _add_tx(db, "餐饮", 500)
        db.close()

        resp = client.get("/reports/budget-execution")
        data = resp.json()
        assert data["by_category"][0]["level"] == "L1"  # 餐饮默认L1

    def test_months_param_limit(self):
        """months参数限制1-12"""
        db = TestingSessionLocal()
        _set_budgets(db, [{"category": "餐饮", "monthly_limit": 1000, "level": "L1"}])
        _add_tx(db, "餐饮", 500)
        db.close()

        resp = client.get("/reports/budget-execution?months=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["trend"]) >= 1  # clamped to 1

        resp = client.get("/reports/budget-execution?months=20")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["trend"]) <= 12
