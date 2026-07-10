"""V2-019 持仓管理测试"""
import pytest
import sys
import os

os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
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


# ===== 1. 持仓 CRUD =====

class TestPositionCRUD:
    def test_create_position(self, client):
        """创建持仓"""
        resp = client.post("/positions", json={
            "name": "沪深300ETF",
            "symbol": "510300",
            "position_type": "fund",
            "quantity": 1000,
            "avg_cost": 4.5,
            "current_price": 4.8,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] > 0

    def test_list_positions_empty(self, client):
        """空持仓列表"""
        resp = client.get("/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["count"] == 0

    def test_list_positions(self, client):
        """持仓列表"""
        client.post("/positions", json={
            "name": "沪深300", "position_type": "fund",
            "quantity": 1000, "avg_cost": 4.5, "current_price": 4.8,
        })
        resp = client.get("/positions")
        data = resp.json()
        assert data["summary"]["count"] == 1
        assert data["positions"][0]["name"] == "沪深300"

    def test_position_profit_calculation(self, client):
        """持仓盈亏计算"""
        client.post("/positions", json={
            "name": "股票A", "position_type": "stock",
            "quantity": 100, "avg_cost": 50, "current_price": 60,
        })
        resp = client.get("/positions")
        data = resp.json()
        pos = data["positions"][0]
        assert pos["profit"] == 1000  # (60-50)*100
        assert pos["profit_pct"] == 20.0  # 20%

    def test_update_position(self, client):
        """更新持仓价格"""
        resp = client.post("/positions", json={
            "name": "基金A", "position_type": "fund",
            "quantity": 1000, "avg_cost": 1.0, "current_price": 1.0,
        })
        pid = resp.json()["id"]

        resp = client.put(f"/positions/{pid}", json={"current_price": 1.2})
        assert resp.status_code == 200

        resp = client.get("/positions")
        data = resp.json()
        assert data["positions"][0]["current_price"] == 1.2

    def test_close_position(self, client):
        """关闭持仓"""
        resp = client.post("/positions", json={
            "name": "基金B", "position_type": "fund",
            "quantity": 500, "avg_cost": 2.0, "current_price": 2.5,
        })
        pid = resp.json()["id"]

        resp = client.delete(f"/positions/{pid}")
        assert resp.status_code == 200

        # 默认查询 active，不应返回已关闭的
        resp = client.get("/positions?status=active")
        data = resp.json()
        assert data["summary"]["count"] == 0


# ===== 2. 交易记录 =====

class TestTradeRecords:
    def test_buy_trade(self, client):
        """买入交易"""
        resp = client.post("/positions", json={
            "name": "股票C", "position_type": "stock",
            "quantity": 0, "avg_cost": 0, "current_price": 0,
        })
        pid = resp.json()["id"]

        resp = client.post("/positions/trades", json={
            "position_id": pid,
            "trade_type": "buy",
            "quantity": 100,
            "price": 50,
            "trade_date": "2026-07-01",
            "fee": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["remaining_quantity"] == 100

    def test_buy_updates_avg_cost(self, client):
        """买入更新平均成本"""
        resp = client.post("/positions", json={
            "name": "股票D", "position_type": "stock",
            "quantity": 0, "avg_cost": 0, "current_price": 0,
        })
        pid = resp.json()["id"]

        # 第一次买入 100@50
        client.post("/positions/trades", json={
            "position_id": pid, "trade_type": "buy",
            "quantity": 100, "price": 50, "trade_date": "2026-07-01",
        })
        # 第二次买入 100@60
        client.post("/positions/trades", json={
            "position_id": pid, "trade_type": "buy",
            "quantity": 100, "price": 60, "trade_date": "2026-07-05",
        })

        resp = client.get("/positions")
        data = resp.json()
        pos = data["positions"][0]
        assert pos["quantity"] == 200
        assert pos["avg_cost"] == 55  # (50*100 + 60*100) / 200

    def test_sell_trade(self, client):
        """卖出交易"""
        resp = client.post("/positions", json={
            "name": "股票E", "position_type": "stock",
            "quantity": 200, "avg_cost": 50, "current_price": 55,
        })
        pid = resp.json()["id"]

        resp = client.post("/positions/trades", json={
            "position_id": pid, "trade_type": "sell",
            "quantity": 100, "price": 55, "trade_date": "2026-07-10",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["remaining_quantity"] == 100

    def test_sell_all_closes_position(self, client):
        """全部卖出自动关闭持仓"""
        resp = client.post("/positions", json={
            "name": "股票F", "position_type": "stock",
            "quantity": 100, "avg_cost": 50, "current_price": 55,
        })
        pid = resp.json()["id"]

        client.post("/positions/trades", json={
            "position_id": pid, "trade_type": "sell",
            "quantity": 100, "price": 55, "trade_date": "2026-07-10",
        })

        resp = client.get("/positions?status=active")
        data = resp.json()
        assert data["summary"]["count"] == 0

    def test_sell_more_than_owned_fails(self, client):
        """卖出超过持有数量报错"""
        resp = client.post("/positions", json={
            "name": "股票G", "position_type": "stock",
            "quantity": 50, "avg_cost": 50, "current_price": 55,
        })
        pid = resp.json()["id"]

        resp = client.post("/positions/trades", json={
            "position_id": pid, "trade_type": "sell",
            "quantity": 100, "price": 55, "trade_date": "2026-07-10",
        })
        assert resp.status_code == 400


# ===== 3. 交易历史 =====

class TestTradeHistory:
    def test_trade_history(self, client):
        """获取交易历史"""
        resp = client.post("/positions", json={
            "name": "股票H", "position_type": "stock",
            "quantity": 0, "avg_cost": 0, "current_price": 0,
        })
        pid = resp.json()["id"]

        client.post("/positions/trades", json={
            "position_id": pid, "trade_type": "buy",
            "quantity": 100, "price": 50, "trade_date": "2026-07-01",
        })
        client.post("/positions/trades", json={
            "position_id": pid, "trade_type": "buy",
            "quantity": 50, "price": 55, "trade_date": "2026-07-05",
        })

        resp = client.get(f"/positions/{pid}/trades")
        data = resp.json()
        assert data["total_trades"] == 2
        assert len(data["trades"]) == 2

    def test_nonexistent_position(self, client):
        """不存在的持仓返回404"""
        resp = client.get("/positions/9999/trades")
        assert resp.status_code == 404


# ===== 4. 汇总 =====

class TestSummary:
    def test_summary_totals(self, client):
        """汇总数据正确"""
        client.post("/positions", json={
            "name": "基金X", "position_type": "fund",
            "quantity": 1000, "avg_cost": 1.0, "current_price": 1.2,
        })
        client.post("/positions", json={
            "name": "基金Y", "position_type": "fund",
            "quantity": 500, "avg_cost": 2.0, "current_price": 2.5,
        })

        resp = client.get("/positions")
        data = resp.json()
        summary = data["summary"]
        assert summary["count"] == 2
        assert summary["total_value"] == 1200 + 1250  # 1000*1.2 + 500*2.5
        assert summary["total_cost"] == 1000 + 1000  # 1000*1.0 + 500*2.0
