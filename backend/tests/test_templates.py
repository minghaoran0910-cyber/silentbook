"""V2-008 预算模板 - 测试套件"""
import os

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_tpl_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

import pytest
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_mod
from app.database import Base, get_db, Setting
from app.main import app

main_mod.RATE_LIMIT_ENABLED = False

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


@pytest.fixture(scope="function")
def auth(client):
    r = client.post(
        "/auth/register",
        json={"email": "templates@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ===== 模板列表 =====

class TestListTemplates:
    def test_list_all_templates(self, client, auth):
        """GET /budgets/templates 返回三个模板"""
        resp = client.get("/budgets/templates", headers=auth)
        assert resp.status_code == 200
        templates = resp.json()
        assert len(templates) == 3
        keys = {t["key"] for t in templates}
        assert keys == {"frugal", "balanced", "loose"}

    def test_template_has_required_fields(self, client, auth):
        """每个模板包含必要字段"""
        resp = client.get("/budgets/templates", headers=auth)
        for t in resp.json():
            assert "key" in t
            assert "name" in t
            assert "description" in t
            assert "monthly_total" in t
            assert "category_count" in t
            assert "level_summary" in t
            assert set(t["level_summary"].keys()) == {"L1", "L2", "L3"}

    def test_template_names(self, client, auth):
        """模板中文名称正确"""
        resp = client.get("/budgets/templates", headers=auth)
        names = {t["key"]: t["name"] for t in resp.json()}
        assert names["frugal"] == "节俭型"
        assert names["balanced"] == "均衡型"
        assert names["loose"] == "宽松型"

    def test_template_level_summary_sums_match_total(self, client, auth):
        """level_summary 之和等于 monthly_total"""
        resp = client.get("/budgets/templates", headers=auth)
        for t in resp.json():
            level_sum = sum(t["level_summary"].values())
            assert level_sum == t["monthly_total"], f"{t['key']}: level sum {level_sum} != total {t['monthly_total']}"


# ===== 模板详情 =====

class TestGetTemplate:
    def test_get_frugal_template(self, client, auth):
        """获取节俭型模板详情"""
        resp = client.get("/budgets/templates/frugal", headers=auth)
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

    def test_get_balanced_template(self, client, auth):
        """获取均衡型模板详情"""
        resp = client.get("/budgets/templates/balanced", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "balanced"
        assert data["name"] == "均衡型"

    def test_get_loose_template(self, client, auth):
        """获取宽松型模板详情"""
        resp = client.get("/budgets/templates/loose", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "loose"
        assert data["name"] == "宽松型"

    def test_get_nonexistent_template(self, client, auth):
        """获取不存在的模板返回 404"""
        resp = client.get("/budgets/templates/nonexistent", headers=auth)
        assert resp.status_code == 404

    def test_template_budgets_sum_matches_total(self, client, auth):
        """模板内各项预算之和等于 monthly_total"""
        for key in ["frugal", "balanced", "loose"]:
            resp = client.get(f"/budgets/templates/{key}", headers=auth)
            data = resp.json()
            budgets_sum = sum(b["monthly_limit"] for b in data["budgets"])
            assert budgets_sum == data["monthly_total"], \
                f"{key}: budgets sum {budgets_sum} != total {data['monthly_total']}"


# ===== 应用模板 =====

class TestApplyTemplate:
    def test_apply_frugal_replaces_budgets(self, client, auth):
        """应用节俭型模板替换现有预算"""
        # 先创建一个预算
        client.post("/budgets", json={
            "category": "旧分类", "monthly_limit": 999, "level": "L2"
        }, headers=auth)
        # 应用模板
        resp = client.post("/budgets/templates/frugal/apply", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["template"] == "frugal"
        assert data["applied_count"] > 0

        # 旧预算应被替换
        budgets = client.get("/budgets", headers=auth).json()
        categories = [b["category"] for b in budgets]
        assert "旧分类" not in categories
        assert "房租" in categories
        assert "餐饮" in categories

    def test_apply_balanced_template(self, client, auth):
        """应用均衡型模板"""
        resp = client.post("/budgets/templates/balanced/apply", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["template_name"] == "均衡型"
        assert data["applied_count"] == 13  # balanced has 13 categories

    def test_apply_loose_template(self, client, auth):
        """应用宽松型模板"""
        resp = client.post("/budgets/templates/loose/apply", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["template_name"] == "宽松型"
        assert data["applied_count"] == 13  # loose has 13 categories

    def test_apply_nonexistent_template(self, client, auth):
        """应用不存在的模板返回 404"""
        resp = client.post("/budgets/templates/nonexistent/apply", headers=auth)
        assert resp.status_code == 404

    def test_apply_then_budgets_have_levels(self, client, auth):
        """应用模板后预算有 level 字段"""
        client.post("/budgets/templates/balanced/apply", headers=auth)
        budgets = client.get("/budgets", headers=auth).json()
        for b in budgets:
            assert b["level"] in {"L1", "L2", "L3"}

    def test_apply_then_alert_thresholds(self, client, auth):
        """应用模板后预算有 alert_threshold 字段"""
        client.post("/budgets/templates/frugal/apply", headers=auth)
        budgets = client.get("/budgets", headers=auth).json()
        for b in budgets:
            assert "alert_threshold" in b
            assert b["alert_threshold"] > 0

    def test_apply_twice_idempotent(self, client, auth):
        """多次应用同一模板结果一致"""
        client.post("/budgets/templates/frugal/apply", headers=auth)
        first = client.get("/budgets", headers=auth).json()
        client.post("/budgets/templates/frugal/apply", headers=auth)
        second = client.get("/budgets", headers=auth).json()
        assert len(first) == len(second)
        for a, b in zip(first, second):
            assert a["category"] == b["category"]
            assert a["monthly_limit"] == b["monthly_limit"]

    def test_apply_then_levels_endpoint_works(self, client, auth):
        """应用模板后 /budgets/levels 正常工作"""
        client.post("/budgets/templates/balanced/apply", headers=auth)
        resp = client.get("/budgets/levels", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_budget"] > 0
        assert "L1" in data["levels"]
        assert "L2" in data["levels"]
        assert "L3" in data["levels"]

    def test_apply_then_alerts_endpoint_works(self, client, auth):
        """应用模板后 /budgets/alerts 正常工作"""
        client.post("/budgets/templates/frugal/apply", headers=auth)
        resp = client.get("/budgets/alerts", headers=auth)
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "summary" in data

    def test_apply_template_monthly_total_matches(self, client, auth):
        """应用后预算总额等于模板 monthly_total"""
        for key in ["frugal", "balanced", "loose"]:
            client.post(f"/budgets/templates/{key}/apply", headers=auth)
            tpl = client.get(f"/budgets/templates/{key}", headers=auth).json()
            budgets = client.get("/budgets", headers=auth).json()
            actual_total = sum(b["monthly_limit"] for b in budgets)
            assert actual_total == tpl["monthly_total"], \
                f"{key}: applied total {actual_total} != template total {tpl['monthly_total']}"


# ===== 模板间差异 =====

class TestTemplateDifferences:
    def test_frugal_cheaper_than_balanced(self, client, auth):
        """节俭型总额 < 均衡型总额"""
        templates = {t["key"]: t for t in client.get("/budgets/templates", headers=auth).json()}
        assert templates["frugal"]["monthly_total"] < templates["balanced"]["monthly_total"]

    def test_balanced_cheaper_than_loose(self, client, auth):
        """均衡型总额 < 宽松型总额"""
        templates = {t["key"]: t for t in client.get("/budgets/templates", headers=auth).json()}
        assert templates["balanced"]["monthly_total"] < templates["loose"]["monthly_total"]

    def test_all_templates_have_l1_l2_l3(self, client, auth):
        """所有模板都有 L1/L2/L3 分类"""
        for key in ["frugal", "balanced", "loose"]:
            resp = client.get(f"/budgets/templates/{key}", headers=auth)
            data = resp.json()
            levels = {b["level"] for b in data["budgets"]}
            assert levels == {"L1", "L2", "L3"}, f"{key} missing levels: {levels}"
