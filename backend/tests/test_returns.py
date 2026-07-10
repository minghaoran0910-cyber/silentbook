"""V2-020 收益追踪测试"""
import pytest
import sys
import os

os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import date

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


def _create_position(db, name="测试基金", quantity=1000, avg_cost=1.0, current_price=1.2):
    p = Position(
        name=name, position_type="fund",
        quantity=quantity, avg_cost=avg_cost, current_price=current_price,
        status="active"
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


# ===== 1. 无持仓 =====

class TestNoPosition:
    def test_no_positions(self, client):
        """无持仓返回空"""
        resp = client.get("/investment/returns")
        data = resp.json()
        assert data["total_value"] == 0
        assert data["absolute_return"] == 0

    def test_nonexistent_position(self, client):
        """不存在的持仓返回404"""
        resp = client.get("/investment/returns?position_id=9999")
        assert resp.status_code == 404


# ===== 2. 单持仓收益 =====

class TestSinglePosition:
    def test_simple_return(self, client, db_session):
        """简单收益率计算"""
        p = _create_position(db_session, quantity=1000, avg_cost=1.0, current_price=1.2)
        _add_trade(db_session, p.id, "buy", 1000, 1.0, date(2026, 1, 1))

        resp = client.get(f"/investment/returns?position_id={p.id}")
        data = resp.json()
        # 成本 1000, 当前 1200, 收益 20%
        assert data["absolute_return"] == 20.0

    def test_loss_return(self, client, db_session):
        """亏损收益率"""
        p = _create_position(db_session, quantity=1000, avg_cost=1.0, current_price=0.8)
        _add_trade(db_session, p.id, "buy", 1000, 1.0, date(2026, 1, 1))

        resp = client.get(f"/investment/returns?position_id={p.id}")
        data = resp.json()
        assert data["absolute_return"] == -20.0

    def test_no_trades(self, client, db_session):
        """无交易记录时返回提示"""
        p = _create_position(db_session)
        resp = client.get(f"/investment/returns?position_id={p.id}")
        data = resp.json()
        assert "message" in data


# ===== 3. 多交易收益 =====

class TestMultipleTrades:
    def test_buy_and_sell(self, client, db_session):
        """买入+卖出后收益"""
        p = _create_position(db_session, quantity=500, avg_cost=1.0, current_price=1.5)
        _add_trade(db_session, p.id, "buy", 1000, 1.0, date(2026, 1, 1))
        _add_trade(db_session, p.id, "sell", 500, 1.2, date(2026, 3, 1))

        resp = client.get(f"/investment/returns?position_id={p.id}")
        data = resp.json()
        assert "absolute_return" in data
        assert "xirr" in data

    def test_xirr_present(self, client, db_session):
        """XIRR 计算存在"""
        p = _create_position(db_session, quantity=1000, avg_cost=1.0, current_price=1.3)
        _add_trade(db_session, p.id, "buy", 1000, 1.0, date(2026, 1, 1))
        _add_trade(db_session, p.id, "buy", 500, 1.1, date(2026, 4, 1))

        resp = client.get(f"/investment/returns?position_id={p.id}")
        data = resp.json()
        assert "xirr" in data
        assert data["trade_count"] == 2

    def test_annualized_return(self, client, db_session):
        """年化收益率"""
        p = _create_position(db_session, quantity=1000, avg_cost=1.0, current_price=1.2)
        _add_trade(db_session, p.id, "buy", 1000, 1.0, date(2025, 7, 10))

        resp = client.get(f"/investment/returns?position_id={p.id}")
        data = resp.json()
        assert "annualized_return" in data
        assert data["holding_days"] > 0


# ===== 4. 组合收益 =====

class TestPortfolioReturns:
    def test_portfolio_returns(self, client, db_session):
        """全组合收益"""
        _create_position(db_session, "基金A", 1000, 1.0, 1.2)
        _create_position(db_session, "基金B", 500, 2.0, 2.5)

        resp = client.get("/investment/returns")
        data = resp.json()
        assert data["portfolio"] is True
        assert data["position_count"] == 2
        # 总成本 1000 + 1000 = 2000, 总市值 1200 + 1250 = 2450
        assert data["total_cost"] == 2000
        assert data["total_value"] == 2450
        assert data["absolute_return"] == 22.5  # 450/2000 * 100

    def test_portfolio_empty(self, client, db_session):
        """空组合"""
        resp = client.get("/investment/returns")
        data = resp.json()
        assert data["total_value"] == 0
