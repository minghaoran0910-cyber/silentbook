"""V2-024 深度风险分析 测试"""
import pytest
import os

os.environ["DATABASE_URL"] = "sqlite://"

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import date, timedelta

from app.database import Base, get_db, Position, TradeRecord, Account
from app.main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


def _create_account(db):
    account = Account(
        name="测试投资账户",
        account_type="investment",
        purpose="investment",
        balance=100000,
        currency="CNY",
        status="active"
    )
    db.add(account)
    db.commit()
    return account


def _create_position(db, name="测试股票", quantity=100, avg_cost=50.0, current_price=55.0, position_type="stock"):
    pos = Position(
        name=name,
        position_type=position_type,
        quantity=quantity,
        avg_cost=avg_cost,
        current_price=current_price,
        status="active",
    )
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


def _create_trade(db, position_id, trade_type="buy", quantity=100, price=50.0, trade_date=None):
    trade = TradeRecord(
        position_id=position_id,
        trade_type=trade_type,
        quantity=quantity,
        price=price,
        amount=quantity * price,
        trade_date=trade_date or date.today(),
    )
    db.add(trade)
    db.commit()
    return trade


class TestRiskAnalysisEndpoint:
    """测试 /investment/risk-analysis 端点"""

    def test_no_positions(self, db_session):
        """无持仓时返回提示"""
        resp = client.get("/investment/risk-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["risk_metrics"] is None or "message" in data

    def test_basic_response_structure(self, db_session):
        """有持仓时返回完整结构"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(60):
            d = date.today() - timedelta(days=60 - i)
            _create_trade(db_session, pos.id, "buy", 10, 50.0 + i * 0.1, d)

        resp = client.get("/investment/risk-analysis?days=90")
        assert resp.status_code == 200
        data = resp.json()
        
        assert "days" in data
        assert "risk_grade" in data
        assert "var" in data
        assert "drawdown" in data
        assert "risk_metrics" in data
        assert "distribution" in data
        assert "stress_test" in data
        assert "risk_decomposition" in data
        assert "rolling_metrics" in data
        assert "recommendations" in data
        assert "portfolio_value" in data

    def test_var_values(self, db_session):
        """VaR 值应在合理范围"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(90):
            d = date.today() - timedelta(days=90 - i)
            price = 50.0 + (i % 10) * 0.5 - 2.0
            _create_trade(db_session, pos.id, "buy", 10, price, d)

        resp = client.get("/investment/risk-analysis?days=120")
        data = resp.json()
        
        if data.get("var") and data["var"].get("var_95") is not None:
            var_95 = data["var"]["var_95"]
            var_99 = data["var"]["var_99"]
            if var_99 is not None:
                assert var_99 <= var_95 + 0.001

    def test_cvar_more_extreme_than_var(self, db_session):
        """CVaR 应比 VaR 更极端"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(90):
            d = date.today() - timedelta(days=90 - i)
            price = 50.0 + (i % 7) * 0.8 - 2.5
            _create_trade(db_session, pos.id, "buy", 10, price, d)

        resp = client.get("/investment/risk-analysis?days=120")
        data = resp.json()
        
        if data.get("var") and data["var"].get("var_95") is not None:
            var_95 = data["var"]["var_95"]
            cvar_95 = data["var"]["cvar_95"]
            if cvar_95 is not None:
                assert cvar_95 <= var_95 + 0.001

    def test_drawdown_details(self, db_session):
        """回撤分析应包含必要字段"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(60):
            d = date.today() - timedelta(days=60 - i)
            if i < 30:
                price = 50.0 + i * 1.0
            else:
                price = 80.0 - (i - 30) * 0.8
            _create_trade(db_session, pos.id, "buy", 10, price, d)

        resp = client.get("/investment/risk-analysis?days=90")
        data = resp.json()
        
        dd = data.get("drawdown", {})
        assert "current_drawdown" in dd
        assert "max_drawdown" in dd
        assert "avg_recovery_days" in dd
        assert "longest_drawdown_days" in dd
        assert "drawdown_periods" in dd
        assert isinstance(dd["drawdown_periods"], list)

    def test_stress_test_scenarios(self, db_session):
        """压力测试应返回5种情景"""
        _create_account(db_session)
        pos = _create_position(db_session, quantity=100, avg_cost=50, current_price=55)
        
        resp = client.get("/investment/risk-analysis?days=90")
        data = resp.json()
        
        stress = data.get("stress_test", [])
        assert len(stress) == 5
        for s in stress:
            assert "name" in s
            assert "emoji" in s
            assert "shock_pct" in s
            assert "estimated_loss" in s
            assert "remaining_value" in s

    def test_risk_grade(self, db_session):
        """风险评级应在 A-F 范围"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(60):
            d = date.today() - timedelta(days=60 - i)
            _create_trade(db_session, pos.id, "buy", 10, 50.0 + i * 0.05, d)

        resp = client.get("/investment/risk-analysis?days=90")
        data = resp.json()
        
        grade = data.get("risk_grade", {})
        assert grade.get("grade") in ["A", "B", "C", "D", "F"]
        assert "label" in grade
        assert "emoji" in grade
        assert "score" in grade
        assert 0 <= grade["score"] <= 100

    def test_distribution_stats(self, db_session):
        """收益分布统计"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(90):
            d = date.today() - timedelta(days=90 - i)
            price = 50.0 + (i % 5) * 0.3 - 0.5
            _create_trade(db_session, pos.id, "buy", 10, price, d)

        resp = client.get("/investment/risk-analysis?days=120")
        data = resp.json()
        
        dist = data.get("distribution", {})
        if dist.get("total_days"):
            assert dist["total_days"] == dist["positive_days"] + dist["negative_days"] + dist["zero_days"]
            assert 0 <= dist["positive_pct"] <= 100

    def test_risk_decomposition(self, db_session):
        """风险分解应按持仓列出"""
        _create_account(db_session)
        pos1 = _create_position(db_session, "股票A", 100, 50, 55, "stock")
        pos2 = _create_position(db_session, "基金B", 200, 30, 32, "fund")
        
        for i in range(60):
            d = date.today() - timedelta(days=60 - i)
            _create_trade(db_session, pos1.id, "buy", 5, 50.0 + i * 0.1, d)
            _create_trade(db_session, pos2.id, "buy", 10, 30.0 + i * 0.05, d)

        resp = client.get("/investment/risk-analysis?days=90")
        data = resp.json()
        
        decomp = data.get("risk_decomposition", [])
        assert len(decomp) >= 2
        for item in decomp:
            assert "name" in item
            assert "weight" in item
            assert "risk_contribution" in item

    def test_rolling_metrics(self, db_session):
        """滚动指标应包含夏普和波动率"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(90):
            d = date.today() - timedelta(days=90 - i)
            _create_trade(db_session, pos.id, "buy", 10, 50.0 + (i % 10) * 0.2, d)

        resp = client.get("/investment/risk-analysis?days=120")
        data = resp.json()
        
        rolling = data.get("rolling_metrics", {})
        assert "rolling_sharpe" in rolling
        assert "rolling_volatility" in rolling

    def test_recommendations_not_empty(self, db_session):
        """建议列表不应为空"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(60):
            d = date.today() - timedelta(days=60 - i)
            _create_trade(db_session, pos.id, "buy", 10, 50.0 + i * 0.1, d)

        resp = client.get("/investment/risk-analysis?days=90")
        data = resp.json()
        
        recs = data.get("recommendations", [])
        assert len(recs) >= 1

    def test_custom_confidence(self, db_session):
        """自定义置信度参数"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(60):
            d = date.today() - timedelta(days=60 - i)
            _create_trade(db_session, pos.id, "buy", 10, 50.0 + i * 0.1, d)

        resp = client.get("/investment/risk-analysis?days=90&confidence=0.99")
        assert resp.status_code == 200
        data = resp.json()
        assert data["confidence_level"] == 0.99

    def test_insufficient_data(self, db_session):
        """数据不足时返回提示"""
        _create_account(db_session)
        pos = _create_position(db_session)
        for i in range(2):
            d = date.today() - timedelta(days=2 - i)
            _create_trade(db_session, pos.id, "buy", 10, 50.0, d)

        resp = client.get("/investment/risk-analysis?days=30")
        assert resp.status_code == 200


class TestHelperFunctions:
    """测试辅助函数"""

    def test_var_empty_returns(self, db_session):
        from app.main import _calc_var_historical
        assert _calc_var_historical([], 0.95) is None
        assert _calc_var_historical([0.01], 0.95) is None

    def test_var_with_known_data(self, db_session):
        from app.main import _calc_var_historical
        returns = [i * 0.01 - 0.5 for i in range(100)]
        var_95 = _calc_var_historical(returns, 0.95)
        assert var_95 is not None
        assert var_95 < 0

    def test_cvar_empty(self, db_session):
        from app.main import _calc_cvar
        assert _calc_cvar([], 0.95) is None

    def test_cvar_more_extreme(self, db_session):
        from app.main import _calc_var_historical, _calc_cvar
        returns = [i * 0.01 - 0.5 for i in range(100)]
        var = _calc_var_historical(returns, 0.95)
        cvar = _calc_cvar(returns, 0.95)
        assert cvar <= var

    def test_drawdown_details_empty(self, db_session):
        from app.main import _calc_drawdown_details
        result = _calc_drawdown_details([])
        assert result["current_drawdown"] == 0
        assert result["max_drawdown"] == 0

    def test_drawdown_with_peak_and_trough(self, db_session):
        from app.main import _calc_drawdown_details
        series = [
            {"date": "2026-01-01", "value": 100},
            {"date": "2026-01-02", "value": 120},
            {"date": "2026-01-03", "value": 90},
            {"date": "2026-01-04", "value": 110},
            {"date": "2026-01-05", "value": 130},
        ]
        result = _calc_drawdown_details(series)
        assert result["max_drawdown"] > 0
        assert abs(result["max_drawdown"] - 25.0) < 0.1

    def test_stress_test(self, db_session):
        from app.main import _calc_stress_test
        results = _calc_stress_test(100000, [])
        assert len(results) == 5
        assert results[0]["estimated_loss"] == -5000
        assert results[0]["remaining_value"] == 95000

    def test_risk_grade_boundaries(self, db_session):
        from app.main import _calc_risk_grade
        grade = _calc_risk_grade(0.005, 3.0, 1.5, 0.1, 2.0)
        assert grade["grade"] in ["A", "B"]
        
        grade = _calc_risk_grade(0.06, 35.0, -0.5, 0.5, 25.0)
        assert grade["grade"] in ["D", "F"]

    def test_rolling_metrics_insufficient_data(self, db_session):
        from app.main import _calc_rolling_metrics
        result = _calc_rolling_metrics([0.01, -0.02, 0.03], ["d1", "d2", "d3", "d4"], window=30)
        assert result["rolling_sharpe"] == []
        assert result["rolling_volatility"] == []
