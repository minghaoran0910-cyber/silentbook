"""V2-008 预算模板 - 测试套件"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, Setting
from app.main import app

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


# ===== 模板列表 =====

class TestListTemplates:
    def test_list_all_templates(self, client):
        """GET /budgets/templates 返回三个模板"""
        resp = client.get("/budgets/templates")
        assert resp.status_code == 200
        templates = resp.json()
        assert len(templates) == 3
        keys = {t["key"] for t in templates}
        assert keys == {"frugal", "balanced", "loose"}

    def test_template_has_required_fields(self, client):
        """每个模板包含必要字段"""
        resp = client.get("/budgets/templates")
        for t in resp.json():
            assert "key" in t
            assert "name" in t
            assert "description" in t
            assert "monthly_total" in t
            assert "category_count" in t
            assert "level_summary" in t
            assert set(t["level_summary"].keys()) == {"L1", "L2", "L3"}

    def test_template_names(self, client):
        """模板中文名称正确"""
        resp = client.get("/budgets/templates")
        names = {t["key"]: t["name"] for t in resp.json()}
        assert names["frugal"] == "节俭型"
        assert names["balanced"] == "均衡型"
        assert names["loose"] == "宽松型"

    def test_template_level_summary_sums_match_total(self, client):
        """level_summary 之和等于 monthly_total"""
        resp = client.get("/budgets/templates")
        for t in resp.json():
            level_sum = sum(t["level_summary"].values())
            assert level_sum == t["monthly_total"], f"{t['key']}: level sum {level_sum} != total {t['monthly_total']}"


# ===== 模板详情 =====

class TestGetTemplate:
    def test_get_frugal_template(self, client):
        """获取节俭型模板详情"""
        resp = client.get("/budgets/templates/frugal")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "frugal"
        assert data["name"] == "节俭型"
        assert len(data["budgets"]) > 0
        # 所有 budget 都有 category, monthly_limit, level
        for b in data["budgets"]:
            assert "category" in b
            assert "monthly_limit" in b
            assert b["level"] in {"L1", "L2", "L3"}

    def test_get_balanced_template(self, client):
        """获取均衡型模板详情"""
        resp = client.get("/budgets/templates/balanced")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "balanced"
        assert data["name"] == "均衡型"

    def test_get_loose_template(self, client):
        """获取宽松型模板详情"""
        resp = client.get("/budgets/templates/loose")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "loose"
        assert data["name"] == "宽松型"

    def test_get_nonexistent_template(self, client):
        """获取不存在的模板返回 404"""
        resp = client.get("/budgets/templates/nonexistent")
        assert resp.status_code == 404

    def test_template_budgets_sum_matches_total(self, client):
        """模板内各项预算之和等于 monthly_total"""
        for key in ["frugal", "balanced", "loose"]:
            resp = client.get(f"/budgets/templates/{key}")
            data = resp.json()
            budgets_sum = sum(b["monthly_limit"] for b in data["budgets"])
            assert budgets_sum == data["monthly_total"], \
                f"{key}: budgets sum {budgets_sum} != total {data['monthly_total']}"


# ===== 应用模板 =====

class TestApplyTemplate:
    def test_apply_frugal_replaces_budgets(self, client):
        """应用节俭型模板替换现有预算"""
        # 先创建一个预算
        client.post("/budgets", json={
            "category": "旧分类", "monthly_limit": 999, "level": "L2"
        })
        # 应用模板
        resp = client.post("/budgets/templates/frugal/apply")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["template"] == "frugal"
        assert data["applied_count"] > 0

        # 旧预算应被替换
        budgets = client.get("/budgets").json()
        categories = [b["category"] for b in budgets]
        assert "旧分类" not in categories
        assert "房租" in categories
        assert "餐饮" in categories

    def test_apply_balanced_template(self, client):
        """应用均衡型模板"""
        resp = client.post("/budgets/templates/balanced/apply")
        assert resp.status_code == 200
        data = resp.json()
        assert data["template_name"] == "均衡型"
        assert data["applied_count"] == 13  # balanced has 13 categories

    def test_apply_loose_template(self, client):
        """应用宽松型模板"""
        resp = client.post("/budgets/templates/loose/apply")
        assert resp.status_code == 200
        data = resp.json()
        assert data["template_name"] == "宽松型"
        assert data["applied_count"] == 13  # loose has 13 categories

    def test_apply_nonexistent_template(self, client):
        """应用不存在的模板返回 404"""
        resp = client.post("/budgets/templates/nonexistent/apply")
        assert resp.status_code == 404

    def test_apply_then_budgets_have_levels(self, client):
        """应用模板后预算有 level 字段"""
        client.post("/budgets/templates/balanced/apply")
        budgets = client.get("/budgets").json()
        for b in budgets:
            assert b["level"] in {"L1", "L2", "L3"}

    def test_apply_then_alert_thresholds(self, client):
        """应用模板后预算有 alert_threshold 字段"""
        client.post("/budgets/templates/frugal/apply")
        budgets = client.get("/budgets").json()
        for b in budgets:
            assert "alert_threshold" in b
            assert b["alert_threshold"] > 0

    def test_apply_twice_idempotent(self, client):
        """多次应用同一模板结果一致"""
        client.post("/budgets/templates/frugal/apply")
        first = client.get("/budgets").json()
        client.post("/budgets/templates/frugal/apply")
        second = client.get("/budgets").json()
        assert len(first) == len(second)
        for a, b in zip(first, second):
            assert a["category"] == b["category"]
            assert a["monthly_limit"] == b["monthly_limit"]

    def test_apply_then_levels_endpoint_works(self, client):
        """应用模板后 /budgets/levels 正常工作"""
        client.post("/budgets/templates/balanced/apply")
        resp = client.get("/budgets/levels")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_budget"] > 0
        assert "L1" in data["levels"]
        assert "L2" in data["levels"]
        assert "L3" in data["levels"]

    def test_apply_then_alerts_endpoint_works(self, client):
        """应用模板后 /budgets/alerts 正常工作"""
        client.post("/budgets/templates/frugal/apply")
        resp = client.get("/budgets/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "summary" in data

    def test_apply_template_monthly_total_matches(self, client):
        """应用后预算总额等于模板 monthly_total"""
        for key in ["frugal", "balanced", "loose"]:
            client.post(f"/budgets/templates/{key}/apply")
            tpl = client.get(f"/budgets/templates/{key}").json()
            budgets = client.get("/budgets").json()
            actual_total = sum(b["monthly_limit"] for b in budgets)
            assert actual_total == tpl["monthly_total"], \
                f"{key}: applied total {actual_total} != template total {tpl['monthly_total']}"


# ===== 模板间差异 =====

class TestTemplateDifferences:
    def test_frugal_cheaper_than_balanced(self, client):
        """节俭型总额 < 均衡型总额"""
        templates = {t["key"]: t for t in client.get("/budgets/templates").json()}
        assert templates["frugal"]["monthly_total"] < templates["balanced"]["monthly_total"]

    def test_balanced_cheaper_than_loose(self, client):
        """均衡型总额 < 宽松型总额"""
        templates = {t["key"]: t for t in client.get("/budgets/templates").json()}
        assert templates["balanced"]["monthly_total"] < templates["loose"]["monthly_total"]

    def test_all_templates_have_l1_l2_l3(self, client):
        """所有模板都有 L1/L2/L3 分类"""
        for key in ["frugal", "balanced", "loose"]:
            resp = client.get(f"/budgets/templates/{key}")
            data = resp.json()
            levels = {b["level"] for b in data["budgets"]}
            assert levels == {"L1", "L2", "L3"}, f"{key} missing levels: {levels}"
