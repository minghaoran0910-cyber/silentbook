"""
V2-040: 测试分析页和设置页的认证问题修复
确保所有端点在带 auth header 时正常返回数据
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app, get_db
from app.database import Base, User, AnalysisResult, Setting
from app.auth import hash_password, create_token

TEST_DB = "sqlite:///./test_analysis_settings.db"
engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """创建测试用户并返回 auth headers"""
    db = TestingSession()
    user = User(
        email="test-analysis@test.com",
        password_hash=hash_password("testpass"),
        is_active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user)
    db.close()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_analysis():
    """创建示例分析数据"""
    db = TestingSession()
    analyses = [
        AnalysisResult(agent_name="test", analysis_type="consumption", content="消费分析内容"),
        AnalysisResult(agent_name="test", analysis_type="investment", content="投资分析内容"),
        AnalysisResult(agent_name="test", analysis_type="suggestion", content="综合建议内容"),
    ]
    for a in analyses:
        db.add(a)
    db.commit()
    db.close()


class TestAnalysisEndpoints:
    def test_latest_analysis_requires_auth(self, client):
        """无 auth 应返回 401"""
        resp = client.get("/analysis/latest")
        assert resp.status_code == 401

    def test_latest_analysis_with_auth(self, client, auth_headers, sample_analysis):
        """带 auth 应返回分析数据"""
        resp = client.get("/analysis/latest", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["consumption"] == "消费分析内容"
        assert data["investment"] == "投资分析内容"
        assert data["suggestion"] == "综合建议内容"

    def test_analysis_history_requires_auth(self, client):
        """无 auth 应返回 401"""
        resp = client.get("/analysis/history")
        assert resp.status_code == 401

    def test_analysis_history_with_auth(self, client, auth_headers, sample_analysis):
        """带 auth 应返回历史数据"""
        resp = client.get("/analysis/history?limit=5", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0


class TestSettingsEndpoints:
    def test_ai_config_requires_auth(self, client):
        """无 auth 应返回 401"""
        resp = client.get("/settings/ai-config")
        assert resp.status_code == 401

    def test_ai_config_with_auth(self, client, auth_headers):
        """带 auth 应返回配置"""
        resp = client.get("/settings/ai-config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "api_base" in data
        assert "model_name" in data

    def test_update_ai_config(self, client, auth_headers):
        """更新 AI 配置"""
        resp = client.put("/settings/ai-config", headers=auth_headers, json={
            "api_base": "https://test.api.com/v1",
            "model_name": "test-model"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_base"] == "https://test.api.com/v1"
        assert data["model_name"] == "test-model"

    def test_openclaw_binding_requires_auth(self, client):
        """无 auth 应返回 401"""
        resp = client.get("/settings/openclaw-bindding")
        assert resp.status_code == 401

    def test_openclaw_binding_with_auth(self, client, auth_headers):
        """带 auth 应返回绑定状态"""
        resp = client.get("/settings/openclaw-bindding", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "bound" in data
        assert data["bound"] is False

    def test_settings_requires_auth(self, client):
        """无 auth 应返回 401"""
        resp = client.get("/settings")
        assert resp.status_code == 401

    def test_settings_with_auth(self, client, auth_headers):
        """带 auth 应返回设置"""
        resp = client.get("/settings", headers=auth_headers)
        assert resp.status_code == 200

    def test_settings_sources_with_auth(self, client, auth_headers):
        """带 auth 应返回通知源配置"""
        resp = client.get("/settings/sources", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "cmb" in data

    def test_settings_agents_with_auth(self, client, auth_headers):
        """带 auth 应返回 Agent 配置"""
        resp = client.get("/settings/agents", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestMonthlyStats:
    def test_monthly_stats_requires_auth(self, client):
        """无 auth 应返回 401"""
        resp = client.get("/stats/monthly")
        assert resp.status_code == 401

    def test_monthly_stats_with_auth(self, client, auth_headers):
        """带 auth 应返回月度统计"""
        resp = client.get("/stats/monthly", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_income" in data
        assert "total_expense" in data
