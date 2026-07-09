"""负债清单测试（V2-011）"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base, get_db
from app.main import app

# 使用 SQLite 内存数据库测试（StaticPool 保证连接共享同一内存库）
SQLALCHEMY_DATABASE_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    """每个测试前清空所有数据"""
    db = TestingSessionLocal()
    try:
        from app.database import Transaction, Liability, Account, Transfer
        db.query(Transaction).delete()
        db.query(Liability).delete()
        db.query(Transfer).delete()
        db.query(Account).delete()
        db.commit()
    finally:
        db.close()
    yield


def _create_liability(name, liability_type, total=100000, current=50000, monthly=2000, periods=24, rate=5.0, status="active"):
    """辅助函数：创建负债"""
    resp = client.post("/liabilities", json={
        "name": name,
        "liability_type": liability_type,
        "total_amount": total,
        "current_amount": current,
        "interest_rate": rate,
        "monthly_payment": monthly,
        "remaining_periods": periods,
        "status": status
    })
    assert resp.status_code == 200, f"创建负债失败: {resp.text}"
    return resp.json()


def _create_income(amount=10000):
    """辅助函数：创建本月收入"""
    resp = client.post("/transactions", json={
        "amount": amount, "category": "工资", "account": "招商",
        "transaction_type": "income"
    })
    assert resp.status_code == 200
    return resp.json()


# ===== 基础 CRUD 测试 =====

class TestLiabilityCRUD:
    """测试负债 CRUD + 新字段"""

    def test_create_mortgage(self):
        """创建房贷"""
        data = _create_liability("招商房贷", "mortgage", total=2000000, current=1500000, monthly=8000, periods=300)
        assert data["name"] == "招商房贷"
        assert data["liability_type"] == "mortgage"
        assert data["monthly_payment"] == 8000
        assert data["remaining_periods"] == 300

    def test_create_car_loan(self):
        """创建车贷"""
        data = _create_liability("比亚迪车贷", "car_loan", total=150000, current=80000, monthly=3000, periods=27)
        assert data["liability_type"] == "car_loan"

    def test_create_credit_card(self):
        """创建信用卡"""
        data = _create_liability("招行信用卡", "credit_card", total=50000, current=12000, monthly=2000, periods=6, rate=18.0)
        assert data["liability_type"] == "credit_card"

    def test_create_credit_card_installment(self):
        """创建信用卡分期"""
        data = _create_liability("工行分期", "credit_card_installment", total=24000, current=16000, monthly=2000, periods=8, rate=7.2)
        assert data["liability_type"] == "credit_card_installment"

    def test_create_huabei(self):
        """创建花呗"""
        data = _create_liability("支付宝花呗", "huabei", total=5000, current=1500, monthly=500, periods=3, rate=14.6)
        assert data["liability_type"] == "huabei"

    def test_create_baitiao(self):
        """创建白条"""
        data = _create_liability("京东白条", "baitiao", total=3000, current=1000, monthly=500, periods=2, rate=12.0)
        assert data["liability_type"] == "baitiao"

    def test_create_loan(self):
        """创建其他贷款"""
        data = _create_liability("消费贷", "loan", total=100000, current=60000, monthly=2500, periods=24, rate=8.0)
        assert data["liability_type"] == "loan"

    def test_invalid_liability_type(self):
        """无效的负债类型应被拒绝"""
        resp = client.post("/liabilities", json={
            "name": "非法类型",
            "liability_type": "crypto_debt",
            "total_amount": 1000,
            "current_amount": 500,
        })
        assert resp.status_code == 422

    def test_update_monthly_payment(self):
        """更新月供"""
        data = _create_liability("测试贷款", "loan")
        lid = data["id"]
        resp = client.put(f"/liabilities/{lid}", json={"monthly_payment": 1200})
        assert resp.status_code == 200
        assert resp.json()["monthly_payment"] == 1200

    def test_list_with_type_filter(self):
        """按类型筛选负债"""
        _create_liability("房贷", "mortgage")
        _create_liability("车贷", "car_loan")
        resp = client.get("/liabilities", params={"liability_type": "mortgage"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["liability_type"] == "mortgage"


# ===== 负债汇总测试 =====

class TestLiabilitySummary:
    """测试 /liabilities/summary 端点"""

    def test_empty_summary(self):
        """空负债汇总"""
        resp = client.get("/liabilities/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_current_amount"] == 0
        assert data["total_monthly_payment"] == 0
        assert data["total_count"] == 0
        assert data["by_type"] == {}

    def test_summary_single_type(self):
        """单类型负债汇总"""
        _create_liability("房贷A", "mortgage", total=1000000, current=800000, monthly=5000, periods=200)
        resp = client.get("/liabilities/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_current_amount"] == 800000
        assert data["total_monthly_payment"] == 5000
        assert data["total_count"] == 1
        assert data["status_counts"]["active"] == 1
        assert "mortgage" in data["by_type"]
        assert data["by_type"]["mortgage"]["label"] == "房贷"
        assert data["by_type"]["mortgage"]["current_amount"] == 800000

    def test_summary_multi_type(self):
        """多类型负债汇总"""
        _create_liability("房贷", "mortgage", total=1000000, current=800000, monthly=5000, periods=200)
        _create_liability("车贷", "car_loan", total=100000, current=50000, monthly=2000, periods=25)
        _create_liability("花呗", "huabei", total=3000, current=1000, monthly=500, periods=2)
        _create_liability("已还清", "loan", total=50000, current=0, monthly=0, periods=0, status="paid")

        resp = client.get("/liabilities/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_current_amount"] == 851000
        assert data["total_monthly_payment"] == 7500
        assert data["total_count"] == 4
        assert data["status_counts"]["active"] == 3
        assert data["status_counts"]["paid"] == 1
        assert "mortgage" in data["by_type"]
        assert "car_loan" in data["by_type"]
        assert "huabei" in data["by_type"]
        assert "loan" in data["by_type"]

    def test_summary_interest_estimate(self):
        """利息估算（刚好持平）"""
        _create_liability("贷款", "loan", total=100000, current=60000, monthly=2500, periods=24, rate=8.0)
        # 利息估算 = 2500 × 24 - 60000 = 0
        resp = client.get("/liabilities/summary")
        data = resp.json()
        assert data["total_interest_estimate"] == 0

    def test_summary_interest_estimate_positive(self):
        """正利息估算"""
        _create_liability("贷款", "loan", total=100000, current=60000, monthly=3000, periods=24, rate=8.0)
        # 利息估算 = 3000 × 24 - 60000 = 12000
        resp = client.get("/liabilities/summary")
        data = resp.json()
        assert data["total_interest_estimate"] == 12000


# ===== 负债率监控测试 =====

class TestDebtRatio:
    """测试 /liabilities/debt-ratio 端点"""

    def test_no_income_no_debt(self):
        """无收入无负债"""
        resp = client.get("/liabilities/debt-ratio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["debt_ratio"] == 0
        assert data["alert_level"] == "unknown"

    def test_safe_ratio(self):
        """安全负债率 (<30%)"""
        _create_income(10000)
        _create_liability("小额贷款", "loan", total=20000, current=10000, monthly=2000, periods=5)
        resp = client.get("/liabilities/debt-ratio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["monthly_income"] == 10000
        assert data["total_monthly_payment"] == 2000
        assert data["debt_ratio"] == 20.0
        assert data["alert_level"] == "safe"
        assert data["is_over_threshold"] is False

    def test_notice_ratio(self):
        """注意区间 (30-40%)"""
        _create_income(10000)
        _create_liability("贷款", "loan", total=50000, current=30000, monthly=3500, periods=10)
        resp = client.get("/liabilities/debt-ratio")
        data = resp.json()
        assert data["debt_ratio"] == 35.0
        assert data["alert_level"] == "notice"
        assert data["is_over_threshold"] is False

    def test_warning_ratio(self):
        """预警区间 (40-60%)"""
        _create_income(10000)
        _create_liability("贷款", "loan", total=80000, current=50000, monthly=4500, periods=12)
        resp = client.get("/liabilities/debt-ratio")
        data = resp.json()
        assert data["debt_ratio"] == 45.0
        assert data["alert_level"] == "warning"
        assert data["is_over_threshold"] is True

    def test_critical_ratio(self):
        """严重预警 (>=60%)"""
        _create_income(10000)
        _create_liability("房贷", "mortgage", total=500000, current=400000, monthly=7000, periods=60)
        resp = client.get("/liabilities/debt-ratio")
        data = resp.json()
        assert data["debt_ratio"] == 70.0
        assert data["alert_level"] == "critical"
        assert data["is_over_threshold"] is True

    def test_paid_debt_excluded(self):
        """已还清的负债不计入月供"""
        _create_income(10000)
        _create_liability("活跃贷款", "loan", total=30000, current=15000, monthly=3000, periods=5)
        _create_liability("已还清", "loan", total=20000, current=0, monthly=2000, periods=0, status="paid")
        resp = client.get("/liabilities/debt-ratio")
        data = resp.json()
        assert data["total_monthly_payment"] == 3000
        assert data["debt_ratio"] == 30.0
        assert data["active_liability_count"] == 1

    def test_debt_ratio_by_type(self):
        """按类型分组的月供"""
        _create_income(20000)
        _create_liability("房贷", "mortgage", total=1000000, current=800000, monthly=5000, periods=200)
        _create_liability("车贷", "car_loan", total=100000, current=50000, monthly=2000, periods=25)
        resp = client.get("/liabilities/debt-ratio")
        data = resp.json()
        assert "房贷" in data["by_type"]
        assert data["by_type"]["房贷"]["monthly_payment"] == 5000
        assert "车贷" in data["by_type"]
        assert data["by_type"]["车贷"]["monthly_payment"] == 2000
        assert data["debt_ratio"] == 35.0  # (5000+2000)/20000*100


# ===== 集成测试 =====

class TestLiabilityIntegration:
    """集成测试：完整负债管理流程"""

    def test_full_workflow(self):
        """完整流程：创建 → 查询 → 汇总 → 负债率 → 更新 → 删除"""
        # 1. 创建多种负债
        _create_liability("房贷", "mortgage", total=1000000, current=800000, monthly=5000, periods=200)
        _create_liability("花呗", "huabei", total=3000, current=1000, monthly=500, periods=2)

        # 2. 查列表
        resp = client.get("/liabilities")
        assert len(resp.json()) == 2

        # 3. 查汇总
        resp = client.get("/liabilities/summary")
        data = resp.json()
        assert data["total_current_amount"] == 801000
        assert data["total_monthly_payment"] == 5500
        assert data["total_count"] == 2

        # 4. 添加收入，查负债率
        _create_income(15000)
        resp = client.get("/liabilities/debt-ratio")
        data = resp.json()
        assert data["debt_ratio"] == pytest.approx(36.7, abs=0.1)
        assert data["alert_level"] == "notice"

        # 5. 更新花呗为已还清
        h_id = client.get("/liabilities", params={"liability_type": "huabei"}).json()[0]["id"]
        resp = client.put(f"/liabilities/{h_id}", json={
            "status": "paid", "current_amount": 0, "monthly_payment": 0, "remaining_periods": 0
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "paid"

        # 6. 再查负债率 — 只算房贷
        resp = client.get("/liabilities/debt-ratio")
        data = resp.json()
        assert data["total_monthly_payment"] == 5000
        assert data["active_liability_count"] == 1

        # 7. 删除
        resp = client.delete(f"/liabilities/{h_id}")
        assert resp.status_code == 200

        # 8. 确认删除
        resp = client.get("/liabilities")
        assert len(resp.json()) == 1
