"""V2-022 支出结构报表测试"""
import pytest
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import get_db, Base, Transaction, Setting

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_expense_struct.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
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


class TestExpenseStructure:
    """支出结构报表核心测试"""

    def test_empty_month(self):
        """当月无支出时返回空结构"""
        resp = client.get("/reports/expense-structure")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_expense"] == 0
        assert data["summary"]["l1_amount"] == 0
        assert data["structure_health"]["level"] == "empty"

    def test_basic_structure(self):
        """基本三级分类：L1(餐饮1000) + L2(咖啡200) + L3(游戏300)"""
        db = TestingSessionLocal()
        _add_tx(db, "餐饮", 1000)
        _add_tx(db, "咖啡", 200)
        _add_tx(db, "游戏", 300)
        db.close()

        resp = client.get("/reports/expense-structure")
        data = resp.json()

        assert data["summary"]["total_expense"] == 1500
        assert data["summary"]["l1_amount"] == 1000
        assert data["summary"]["l2_amount"] == 200
        assert data["summary"]["l3_amount"] == 300
        assert data["summary"]["l1_pct"] == pytest.approx(66.7, abs=0.1)
        assert data["summary"]["l2_pct"] == pytest.approx(13.3, abs=0.1)
        assert data["summary"]["l3_pct"] == pytest.approx(20.0, abs=0.1)

    def test_by_level_detail(self):
        """by_level 包含分类明细和百分比"""
        db = TestingSessionLocal()
        _add_tx(db, "餐饮", 800)
        _add_tx(db, "交通", 200)
        _add_tx(db, "咖啡", 150)
        db.close()

        resp = client.get("/reports/expense-structure")
        data = resp.json()

        l1 = data["by_level"]["L1"]
        assert l1["label"] == "必要支出"
        assert l1["amount"] == 1000  # 餐饮800 + 交通200
        # 咖啡是 L2
        l2 = data["by_level"]["L2"]
        assert l2["amount"] == 150
        # 检查 L1 分类明细
        cats = {c["category"]: c["amount"] for c in l1["categories"]}
        assert cats["餐饮"] == 800
        assert cats["交通"] == 200

    def test_health_excellent(self):
        """L1=50% L2=30% L3=20% → 结构优秀/健康"""
        db = TestingSessionLocal()
        _add_tx(db, "餐饮", 500)  # L1
        _add_tx(db, "咖啡", 300)  # L2
        _add_tx(db, "游戏", 200)  # L3
        db.close()

        resp = client.get("/reports/expense-structure")
        data = resp.json()
        # L1=50% L2=30% L3=20% → 都在理想区间
        assert data["structure_health"]["score"] >= 65

    def test_health_danger(self):
        """L3>40% → 结构需改善"""
        db = TestingSessionLocal()
        _add_tx(db, "餐饮", 300)   # L1
        _add_tx(db, "咖啡", 100)   # L2
        _add_tx(db, "游戏", 400)   # L3
        _add_tx(db, "购物", 300)   # L3
        db.close()

        resp = client.get("/reports/expense-structure")
        data = resp.json()
        # L3 = 700/1100 = 63.6%
        assert data["structure_health"]["level"] == "danger"

    def test_trend_analysis(self):
        """趋势分析包含多个月份"""
        db = TestingSessionLocal()
        # 当月
        _add_tx(db, "餐饮", 1000, days_ago=0)
        # 30天前（上月）
        _add_tx(db, "餐饮", 800, days_ago=35)
        _add_tx(db, "游戏", 200, days_ago=35)
        db.close()

        resp = client.get("/reports/expense-structure?months=2")
        data = resp.json()
        assert len(data["trend"]) == 2
        # 当月趋势
        curr = data["trend"][-1]
        assert curr["total"] == 1000

    def test_mom_change(self):
        """环比分析：有上月数据时计算环比"""
        db = TestingSessionLocal()
        # 当月
        _add_tx(db, "餐饮", 1200, days_ago=0)
        # 上月
        _add_tx(db, "餐饮", 1000, days_ago=35)
        db.close()

        resp = client.get("/reports/expense-structure?months=2")
        data = resp.json()
        assert data["mom_change"] is not None
        assert data["mom_change"]["total_change"] == 200  # 1200-1000
        assert data["mom_change"]["total_change_pct"] == pytest.approx(20.0, abs=0.1)

    def test_top_categories(self):
        """Top 分类按金额降序"""
        db = TestingSessionLocal()
        _add_tx(db, "餐饮", 1000)
        _add_tx(db, "交通", 500)
        _add_tx(db, "游戏", 300)
        _add_tx(db, "咖啡", 200)
        db.close()

        resp = client.get("/reports/expense-structure")
        data = resp.json()
        top = data["top_categories"]
        assert len(top) == 4
        assert top[0]["category"] == "餐饮"
        assert top[0]["level"] == "L1"
        assert top[2]["category"] == "游戏"
        assert top[2]["level"] == "L3"

    def test_custom_budget_level_override(self):
        """预算配置可覆盖默认分类级别"""
        db = TestingSessionLocal()
        # 把"咖啡"从 L2 覆盖为 L3
        _set_budgets(db, [{"category": "咖啡", "monthly_limit": 500, "level": "L3"}])
        _add_tx(db, "咖啡", 200)
        db.close()

        resp = client.get("/reports/expense-structure")
        data = resp.json()
        assert data["by_level"]["L3"]["amount"] == 200
        assert data["by_level"]["L2"]["amount"] == 0

    def test_unknown_category_defaults_to_l2(self):
        """未映射分类默认归入 L2"""
        db = TestingSessionLocal()
        _add_tx(db, "未知分类", 500)
        db.close()

        resp = client.get("/reports/expense-structure")
        data = resp.json()
        assert data["by_level"]["L2"]["amount"] == 500

    def test_year_month_params(self):
        """指定年月参数"""
        db = TestingSessionLocal()
        _add_tx(db, "餐饮", 1000, days_ago=0)
        db.close()

        now = datetime.utcnow()
        resp = client.get(f"/reports/expense-structure?year={now.year}&month={now.month}")
        data = resp.json()
        assert data["year"] == now.year
        assert data["month"] == now.month
        assert data["summary"]["total_expense"] == 1000

    def test_structure_health_has_suggestions(self):
        """健康度评估包含改善建议"""
        db = TestingSessionLocal()
        _add_tx(db, "餐饮", 500)
        _add_tx(db, "游戏", 500)  # L3 占比 50%
        db.close()

        resp = client.get("/reports/expense-structure")
        data = resp.json()
        suggestions = data["structure_health"]["suggestions"]
        assert len(suggestions) > 0

    def test_no_mom_when_single_month(self):
        """只查一个月时无环比"""
        db = TestingSessionLocal()
        _add_tx(db, "餐饮", 1000)
        db.close()

        resp = client.get("/reports/expense-structure?months=1")
        data = resp.json()
        assert data["mom_change"] is None

    def test_ideal_range_in_by_level(self):
        """by_level 包含理想区间"""
        resp = client.get("/reports/expense-structure")
        data = resp.json()
        assert "ideal_range" in data["by_level"]["L1"]
        assert "ideal_range" in data["by_level"]["L2"]
        assert "ideal_range" in data["by_level"]["L3"]

    def test_transaction_count(self):
        """summary 包含交易笔数"""
        db = TestingSessionLocal()
        _add_tx(db, "餐饮", 100)
        _add_tx(db, "餐饮", 200)
        _add_tx(db, "咖啡", 50)
        db.close()

        resp = client.get("/reports/expense-structure")
        data = resp.json()
        assert data["summary"]["transaction_count"] == 3
        assert data["summary"]["category_count"] == 2
