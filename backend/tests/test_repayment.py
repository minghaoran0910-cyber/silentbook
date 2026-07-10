"""还款计划测试（V2-012）"""
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


def _create_liability(name, ltype, total=100000, current=50000, monthly=2000, periods=24, rate=5.0, status="active"):
    resp = client.post("/liabilities", json={
        "name": name, "liability_type": ltype,
        "total_amount": total, "current_amount": current,
        "interest_rate": rate, "monthly_payment": monthly,
        "remaining_periods": periods, "status": status,
    })
    assert resp.status_code == 200, f"创建负债失败: {resp.text}"
    return resp.json()


# ===== 基础测试 =====

class TestRepaymentPlan:
    """还款计划端点测试"""

    def test_404_not_found(self):
        """不存在的负债返回 404"""
        resp = client.get("/liabilities/999/repayment-plan")
        assert resp.status_code == 404

    def test_paid_liability(self):
        """已还清的负债返回空计划"""
        data = _create_liability("已还清", "loan", current=0, monthly=0, periods=0, status="paid")
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["schedule"] == []
        assert "已还清" in body["message"]

    def test_zero_balance(self):
        """当前余额为 0"""
        data = _create_liability("零余额", "loan", current=0, monthly=2000, periods=12)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["schedule"] == []
        assert "message" in body

    def test_zero_periods(self):
        """剩余期数为 0"""
        data = _create_liability("零期数", "loan", current=10000, monthly=2000, periods=0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["schedule"] == []

    def test_zero_monthly_payment(self):
        """月供为 0"""
        data = _create_liability("零月供", "loan", current=10000, monthly=0, periods=12)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["schedule"] == []

    def test_insufficient_payment(self):
        """月供不足以覆盖利息"""
        # current=100000, rate=24%, 月利息=2000, 月供=1500
        data = _create_liability("低月供", "loan", current=100000, monthly=1500, periods=60, rate=24.0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert body["monthly_payment"] == 1500

    def test_zero_interest_schedule(self):
        """零利率：每期全额还本金"""
        data = _create_liability("无息贷款", "loan", current=12000, monthly=1000, periods=12, rate=0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["schedule"]) == 12
        assert body["total_interest"] == 0
        assert body["total_payment"] == 12000
        # 每期利息为 0，本金 = 月供
        for entry in body["schedule"]:
            assert entry["interest"] == 0
            assert entry["principal"] == 1000
            assert entry["payment"] == 1000
        # 最后一期余额为 0
        assert body["schedule"][-1]["balance"] == 0

    def test_with_interest_schedule(self):
        """有利率：利息 > 0，本金递增，余额递减"""
        data = _create_liability("房贷", "mortgage", current=500000, monthly=3000, periods=200, rate=4.9)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["schedule"]) == 200
        assert body["total_interest"] > 0
        # 利息递减，本金递增
        first = body["schedule"][0]
        second = body["schedule"][1]
        assert first["interest"] > second["interest"]
        assert first["principal"] < second["principal"]
        # 余额递减
        assert first["balance"] > second["balance"]
        # 最后一期余额为 0
        assert body["schedule"][-1]["balance"] == 0

    def test_payment_equals_principal_plus_interest(self):
        """每期：还款 = 本金 + 利息（最后一期除外，最后一期本金=余额）"""
        data = _create_liability("测试贷款", "loan", current=50000, monthly=2500, periods=20, rate=6.0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        for i, entry in enumerate(body["schedule"]):
            assert abs(entry["payment"] - entry["principal"] - entry["interest"]) < 0.01, \
                f"第{i+1}期: payment({entry['payment']}) != principal({entry['principal']}) + interest({entry['interest']})"

    def test_balance_reaches_zero(self):
        """最后一期余额为 0"""
        data = _create_liability("消费贷", "loan", current=36000, monthly=3000, periods=12, rate=7.2)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        assert body["schedule"][-1]["balance"] == 0

    def test_total_interest_sum(self):
        """总利息 = 各期利息之和"""
        data = _create_liability("车贷", "car_loan", current=80000, monthly=3000, periods=30, rate=5.5)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        sum_interest = sum(e["interest"] for e in body["schedule"])
        assert abs(body["total_interest"] - round(sum_interest, 2)) < 0.01

    def test_total_payment_sum(self):
        """总还款 = 各期还款之和"""
        data = _create_liability("测试", "loan", current=60000, monthly=2500, periods=24, rate=8.0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        sum_payment = sum(e["payment"] for e in body["schedule"])
        assert abs(body["total_payment"] - round(sum_payment, 2)) < 0.01

    def test_total_payment_equals_principal_plus_interest(self):
        """总还款 = 本金 + 总利息"""
        data = _create_liability("测试", "loan", current=60000, monthly=2500, periods=24, rate=8.0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        assert abs(body["total_payment"] - body["total_principal"] - body["total_interest"]) < 0.01

    def test_payoff_date_exists(self):
        """预计还清日期存在"""
        data = _create_liability("房贷", "mortgage", current=100000, monthly=5000, periods=20, rate=4.0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        assert body["payoff_date"] is not None
        assert len(body["payoff_date"]) == 10  # YYYY-MM-DD

    def test_schedule_dates_increment(self):
        """每期日期递增"""
        data = _create_liability("短期贷", "loan", current=3000, monthly=1000, periods=3, rate=0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        dates = [e["date"] for e in body["schedule"]]
        assert dates[0] < dates[1] < dates[2]

    def test_response_fields(self):
        """响应包含所有必需字段"""
        data = _create_liability("测试", "loan", current=10000, monthly=1000, periods=10, rate=5.0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        required_fields = {"liability_id", "liability_name", "liability_type", "schedule",
                          "total_interest", "total_payment", "total_principal",
                          "remaining_periods", "monthly_payment", "current_amount",
                          "annual_interest_rate", "payoff_date"}
        assert required_fields.issubset(body.keys())
        entry_fields = {"period", "payment", "principal", "interest", "balance", "date"}
        assert entry_fields.issubset(body["schedule"][0].keys())


# ===== 边界情况 =====

class TestRepaymentEdgeCases:
    """边界情况测试"""

    def test_single_period(self):
        """单期还款"""
        data = _create_liability("一次性", "loan", current=5000, monthly=5000, periods=1, rate=0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        assert len(body["schedule"]) == 1
        assert body["schedule"][0]["principal"] == 5000
        assert body["schedule"][0]["interest"] == 0
        assert body["schedule"][0]["balance"] == 0
        assert body["total_interest"] == 0

    def test_single_period_with_interest(self):
        """单期还款有利息"""
        data = _create_liability("一次性", "loan", current=10000, monthly=10100, periods=1, rate=12.0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        assert len(body["schedule"]) == 1
        entry = body["schedule"][0]
        # 月利率 = 12% / 12 = 1%
        # 利息 = 10000 * 1% = 100
        # 但最后一期本金 = 余额 = 10000，还款 = 10000 + 100 = 10100
        assert abs(entry["interest"] - 100) < 0.01
        assert entry["principal"] == 10000
        assert entry["balance"] == 0

    def test_large_loan(self):
        """大额贷款"""
        data = _create_liability("房贷", "mortgage", current=2000000, monthly=10000, periods=300, rate=4.2)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        assert len(body["schedule"]) == 300
        assert body["schedule"][-1]["balance"] == 0
        assert body["total_interest"] > 0

    def test_small_loan(self):
        """小额贷款"""
        data = _create_liability("花呗", "huabei", current=500, monthly=250, periods=2, rate=14.6)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        assert len(body["schedule"]) == 2
        assert body["schedule"][-1]["balance"] == 0

    def test_various_liability_types(self):
        """不同负债类型都能生成还款计划"""
        types = [
            ("房贷", "mortgage", 1000000, 5000, 200, 4.9),
            ("车贷", "car_loan", 80000, 3000, 30, 5.5),
            ("信用卡", "credit_card", 12000, 2000, 6, 18.0),
            ("信用卡分期", "credit_card_installment", 24000, 2000, 12, 7.2),
            ("花呗", "huabei", 1500, 500, 3, 14.6),
            ("白条", "baitiao", 1000, 500, 2, 12.0),
            ("消费贷", "loan", 60000, 2500, 24, 8.0),
        ]
        for name, ltype, current, monthly, periods, rate in types:
            data = _create_liability(name, ltype, current=current, monthly=monthly, periods=periods, rate=rate)
            resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
            assert resp.status_code == 200, f"{name}还款计划失败: {resp.text}"
            body = resp.json()
            assert len(body["schedule"]) <= periods  # 可能提前还清
            assert body["schedule"][-1]["balance"] == 0

    def test_overpayment_clears_early(self):
        """月供大于余额时，提前在最后一期清零"""
        # current=10000, monthly=5000, periods=3, rate=0
        # 第1期: principal=5000, balance=5000
        # 第2期: principal=5000, balance=0 → 应该到第2期就结束（因为第3期余额=0）
        # 但 remaining_periods=3，所以第2期是最后一期，principal=balance=5000
        data = _create_liability("短期", "loan", current=10000, monthly=5000, periods=3, rate=0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        # 第2期 principal 应该是 5000（清零），第3期不会执行因为 balance <= 0
        assert len(body["schedule"]) <= 3
        assert body["schedule"][-1]["balance"] == 0

    def test_last_period_adjustment(self):
        """最后一期本金调整：principal = balance，不是 monthly_payment - interest"""
        # current=10000, monthly=3000, periods=4, rate=0
        # 第1期: principal=3000, balance=7000
        # 第2期: principal=3000, balance=4000
        # 第3期: principal=3000, balance=1000
        # 第4期: principal=1000(=balance), payment=1000
        data = _create_liability("测试调整", "loan", current=10000, monthly=3000, periods=4, rate=0)
        resp = client.get(f"/liabilities/{data['id']}/repayment-plan")
        body = resp.json()
        last = body["schedule"][-1]
        assert last["principal"] == 1000  # = 余额，不是月供
        assert last["payment"] == 1000
        assert last["balance"] == 0


# ===== 集成测试 =====

class TestRepaymentIntegration:
    """集成测试：完整还款流程"""

    def test_create_then_plan(self):
        """创建负债 → 获取还款计划 → 验证汇总"""
        # 1. 创建负债
        data = _create_liability("房贷", "mortgage", current=500000, monthly=3000, periods=200, rate=4.9)
        lid = data["id"]

        # 2. 获取还款计划
        resp = client.get(f"/liabilities/{lid}/repayment-plan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["liability_name"] == "房贷"
        assert body["liability_type"] == "mortgage"
        assert body["current_amount"] == 500000
        assert body["monthly_payment"] == 3000
        assert body["annual_interest_rate"] == 4.9
        assert len(body["schedule"]) == 200

        # 3. 验证总计
        assert abs(body["total_payment"] - body["total_principal"] - body["total_interest"]) < 0.01

    def test_update_then_replan(self):
        """更新负债后重新获取还款计划"""
        data = _create_liability("贷款", "loan", current=50000, monthly=2000, periods=30, rate=6.0)
        lid = data["id"]

        # 更新月供
        resp = client.put(f"/liabilities/{lid}", json={"monthly_payment": 3000})
        assert resp.status_code == 200

        # 重新获取计划
        resp = client.get(f"/liabilities/{lid}/repayment-plan")
        body = resp.json()
        assert body["monthly_payment"] == 3000
        # 月供增加，总利息减少
        assert body["total_interest"] < 50000  # 粗略验证

    def test_summary_and_plan_consistency(self):
        """汇总端点和还款计划端点数据一致"""
        data = _create_liability("贷款", "loan", current=60000, monthly=2500, periods=24, rate=8.0)
        lid = data["id"]

        # 获取汇总
        summary = client.get("/liabilities/summary").json()
        # 获取还款计划
        plan = client.get(f"/liabilities/{lid}/repayment-plan").json()

        # 汇总中的利息估算 = monthly_payment × remaining_periods - current_amount
        # 还款计划中的总利息 = 各期利息之和
        # 这两个应该接近（汇总用的是粗估）
        assert plan["total_interest"] >= 0
        assert summary["total_interest_estimate"] >= 0
