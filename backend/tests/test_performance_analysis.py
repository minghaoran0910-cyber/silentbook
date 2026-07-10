"""V2-023 收益率分析（高级组合绩效分析）测试"""
import pytest
import sys
import os

os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import date, timedelta

from app.database import Base, get_db, Position, TradeRecord
from app.main import app

engine = create_engine(
    "sqlite://",
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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_position(db, name="测试基金", quantity=1000, avg_cost=1.0,
                     current_price=1.2, position_type="fund", status="active"):
    p = Position(
        name=name, position_type=position_type,
        quantity=quantity, avg_cost=avg_cost, current_price=current_price,
        status=status
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _add_trade(db, position_id, trade_type, quantity, price, trade_date, fee=0):
    t = TradeRecord(
        position_id=position_id, trade_type=trade_type,
        quantity=quantity, price=price, amount=quantity * price,
        fee=fee, trade_date=trade_date
    )
    db.add(t)
    db.commit()
    return t


# ===== 1. 空数据/边界情况 =====

class TestEmptyData:
    def test_no_positions(self, client):
        """无持仓返回提示"""
        resp = client.get("/investment/performance-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "无有效持仓数据"
        assert data["metrics"] is None

    def test_closed_positions_only(self, client, db_session):
        """只有已关闭持仓"""
        _create_position(db_session, status="closed")
        resp = client.get("/investment/performance-analysis")
        data = resp.json()
        assert data["metrics"] is None

    def test_min_days_param(self, client, db_session):
        """最小 days 参数(7)"""
        _create_position(db_session, quantity=100, avg_cost=10, current_price=11)
        resp = client.get("/investment/performance-analysis?days=7")
        assert resp.status_code == 200

    def test_invalid_days(self, client):
        """非法 days 参数"""
        resp = client.get("/investment/performance-analysis?days=3")
        assert resp.status_code == 422  # validation error


# ===== 2. 单持仓绩效 =====

class TestSinglePositionPerformance:
    def test_basic_metrics(self, client, db_session):
        """基础指标存在且合理"""
        p = _create_position(db_session, quantity=1000, avg_cost=1.0, current_price=1.2)
        _add_trade(db_session, p.id, "buy", 1000, 1.0, date.today() - timedelta(days=90))

        resp = client.get("/investment/performance-analysis?days=90")
        data = resp.json()
        
        assert data["metrics"] is not None
        m = data["metrics"]
        assert "total_return" in m
        assert "annualized_return" in m
        assert "sharpe_ratio" in m
        assert "sortino_ratio" in m
        assert "max_drawdown" in m
        assert "annualized_volatility" in m
        assert "risk_level" in m
        assert m["total_return"] > 0  # 1.0→1.2 盈利

    def test_profitable_position(self, client, db_session):
        """盈利持仓：收益率>0"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=15)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=180))

        resp = client.get("/investment/performance-analysis?days=180")
        m = resp.json()["metrics"]
        assert m["total_return"] == pytest.approx(50.0, abs=5)

    def test_losing_position(self, client, db_session):
        """亏损持仓：收益率<0"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=7)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=180))

        resp = client.get("/investment/performance-analysis?days=180")
        m = resp.json()["metrics"]
        assert m["total_return"] < 0

    def test_max_drawdown_range(self, client, db_session):
        """最大回撤在 0-100% 之间"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=12)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=90))

        resp = client.get("/investment/performance-analysis?days=90")
        m = resp.json()["metrics"]
        assert 0 <= m["max_drawdown"] <= 100


# ===== 3. 多持仓组合 =====

class TestPortfolioPerformance:
    def test_multi_position(self, client, db_session):
        """多持仓组合分析"""
        _create_position(db_session, "股票A", 100, 10, 12, "stock")
        _create_position(db_session, "基金B", 500, 2, 2.5, "fund")
        _create_position(db_session, "债券C", 1000, 1, 1.05, "bond")

        resp = client.get("/investment/performance-analysis?days=90")
        data = resp.json()
        
        assert data["summary"]["position_count"] == 3
        assert len(data["attribution"]["by_position"]) == 3
        assert len(data["attribution"]["by_type"]) == 3

    def test_type_attribution_sums(self, client, db_session):
        """资产类型归因权重之和≈100%"""
        _create_position(db_session, "A", 100, 10, 12, "stock")
        _create_position(db_session, "B", 200, 5, 6, "fund")

        resp = client.get("/investment/performance-analysis?days=60")
        types = resp.json()["attribution"]["by_type"]
        total_weight = sum(t["weight"] for t in types)
        assert total_weight == pytest.approx(100.0, abs=0.1)

    def test_position_attribution_sums(self, client, db_session):
        """持仓归因权重之和≈100%"""
        _create_position(db_session, "A", 100, 10, 12, "stock")
        _create_position(db_session, "B", 300, 5, 6, "fund")

        resp = client.get("/investment/performance-analysis?days=60")
        positions = resp.json()["attribution"]["by_position"]
        total_weight = sum(p["weight"] for p in positions)
        assert total_weight == pytest.approx(100.0, abs=0.1)


# ===== 4. 风险指标 =====

class TestRiskMetrics:
    def test_sharpe_ratio_exists(self, client, db_session):
        """夏普比率存在"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=12)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=180))

        resp = client.get("/investment/performance-analysis?days=180")
        m = resp.json()["metrics"]
        assert m["sharpe_ratio"] is not None

    def test_volatility_non_negative(self, client, db_session):
        """波动率非负"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=11)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=90))

        resp = client.get("/investment/performance-analysis?days=90")
        m = resp.json()["metrics"]
        assert m["annualized_volatility"] >= 0
        assert m["downside_volatility"] >= 0

    def test_risk_level_valid(self, client, db_session):
        """风险等级在有效范围内"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=12)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=90))

        resp = client.get("/investment/performance-analysis?days=90")
        level = resp.json()["metrics"]["risk_level"]
        assert level in ["excellent", "good", "moderate", "poor", "danger", "unknown"]


# ===== 5. 时间段收益率 =====

class TestPeriodReturns:
    def test_period_returns_exist(self, client, db_session):
        """各时间段收益率存在"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=12)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=365))

        resp = client.get("/investment/performance-analysis?days=365")
        pr = resp.json()["period_returns"]
        assert "1w" in pr
        assert "1m" in pr
        assert "3m" in pr
        assert "6m" in pr
        assert "1y" in pr
        assert "ytd" in pr

    def test_short_period(self, client, db_session):
        """短周期（7天）只有近期数据"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=11)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=7))

        resp = client.get("/investment/performance-analysis?days=7")
        pr = resp.json()["period_returns"]
        assert pr["1w"] is not None


# ===== 6. 图表数据 =====

class TestChartData:
    def test_chart_data_exists(self, client, db_session):
        """图表数据存在"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=12)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=90))

        resp = client.get("/investment/performance-analysis?days=90")
        chart = resp.json()["chart_data"]
        assert len(chart) > 0
        assert "date" in chart[0]
        assert "return" in chart[0]

    def test_chart_data_max_points(self, client, db_session):
        """图表数据点不超过90个"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=12)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=365))

        resp = client.get("/investment/performance-analysis?days=365")
        chart = resp.json()["chart_data"]
        assert len(chart) <= 90


# ===== 7. 参数验证 =====

class TestParameters:
    def test_custom_risk_free_rate(self, client, db_session):
        """自定义无风险利率"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=12)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=90))

        resp = client.get("/investment/performance-analysis?days=90&risk_free_rate=0.05")
        m = resp.json()["metrics"]
        assert m["risk_free_rate"] == 5.0

    def test_risk_free_rate_bounds(self, client):
        """无风险利率越界"""
        resp = client.get("/investment/performance-analysis?risk_free_rate=0.5")
        assert resp.status_code == 422

    def test_summary_fields(self, client, db_session):
        """summary 字段完整"""
        p = _create_position(db_session, quantity=1000, avg_cost=10, current_price=12)
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=90))

        resp = client.get("/investment/performance-analysis?days=90")
        s = resp.json()["summary"]
        assert "total_value" in s
        assert "total_cost" in s
        assert "total_profit" in s
        assert "position_count" in s


# ===== 8. 多交易场景 =====

class TestMultipleTrades:
    def test_buy_sell_buy(self, client, db_session):
        """买入→卖出→再买入"""
        p = _create_position(db_session, "股票X", 500, 15, 18, "stock")
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=180))
        _add_trade(db_session, p.id, "sell", 500, 12, date.today() - timedelta(days=90))
        _add_trade(db_session, p.id, "buy", 500, 15, date.today() - timedelta(days=30))

        resp = client.get("/investment/performance-analysis?days=180")
        data = resp.json()
        assert data["metrics"] is not None
        assert data["summary"]["position_count"] == 1

    def test_dividend_trade(self, client, db_session):
        """含分红的交易"""
        p = _create_position(db_session, "红利基金", 1000, 10, 11, "fund")
        _add_trade(db_session, p.id, "buy", 1000, 10, date.today() - timedelta(days=180))
        _add_trade(db_session, p.id, "dividend", 100, 1, date.today() - timedelta(days=60))

        resp = client.get("/investment/performance-analysis?days=180")
        assert resp.status_code == 200
        assert resp.json()["metrics"] is not None
