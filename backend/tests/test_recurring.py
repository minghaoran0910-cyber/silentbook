"""V2-027 固定收支管理测试"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, date, timedelta

from app.main import app, get_db
from app.database import Base, RecurringTransaction, Transaction


TEST_DB = "sqlite:///./test_recurring.db"
engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
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


@pytest.fixture
def db():
    db = TestSession()
    yield db
    db.close()


class TestRecurringCRUD:
    """固定收支 CRUD 测试"""

    def test_create_recurring_income(self):
        """创建固定收入（工资）"""
        resp = client.post("/recurring", json={
            "name": "工资",
            "amount": 15000,
            "category": "工资",
            "transaction_type": "income",
            "frequency": "monthly",
            "day_of_month": 15,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "工资"
        assert data["amount"] == 15000
        assert data["frequency"] == "monthly"
        assert data["day_of_month"] == 15
        assert data["source"] == "manual"
        assert data["is_active"] is True

    def test_create_recurring_expense(self):
        """创建固定支出（房租）"""
        resp = client.post("/recurring", json={
            "name": "房租",
            "amount": 5000,
            "category": "住房",
            "transaction_type": "expense",
            "frequency": "monthly",
            "day_of_month": 1,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["transaction_type"] == "expense"
        assert data["category"] == "住房"

    def test_create_with_dates(self):
        """创建带起止日期的固定收支"""
        resp = client.post("/recurring", json={
            "name": "年度保险",
            "amount": 3000,
            "category": "保险",
            "transaction_type": "expense",
            "frequency": "yearly",
            "day_of_month": 1,
            "start_date": "2026-01-01",
            "end_date": "2028-12-31",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["start_date"] == "2026-01-01"
        assert data["end_date"] == "2028-12-31"

    def test_create_invalid_date_range(self):
        """end_date 早于 start_date 应报错"""
        resp = client.post("/recurring", json={
            "name": "测试",
            "amount": 100,
            "category": "测试",
            "transaction_type": "expense",
            "frequency": "monthly",
            "day_of_month": 1,
            "start_date": "2026-12-01",
            "end_date": "2026-01-01",
        })
        assert resp.status_code == 400

    def test_create_invalid_amount(self):
        """金额 <= 0 应报错"""
        resp = client.post("/recurring", json={
            "name": "测试",
            "amount": 0,
            "category": "测试",
            "transaction_type": "expense",
            "frequency": "monthly",
            "day_of_month": 1,
        })
        assert resp.status_code == 422

    def test_create_invalid_type(self):
        """无效 transaction_type 应报错"""
        resp = client.post("/recurring", json={
            "name": "测试",
            "amount": 100,
            "category": "测试",
            "transaction_type": "transfer",
            "frequency": "monthly",
            "day_of_month": 1,
        })
        assert resp.status_code == 422

    def test_list_recurring(self, db):
        """列表查询"""
        # 创建3条
        for i in range(3):
            rt = RecurringTransaction(
                name=f"测试{i}", amount=100*(i+1), category="测试",
                transaction_type="expense", frequency="monthly",
                day_of_month=i+1, is_active=True
            )
            db.add(rt)
        db.commit()

        resp = client.get("/recurring")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_list_filter_active(self, db):
        """按激活状态筛选"""
        db.add(RecurringTransaction(
            name="活跃", amount=100, category="测试",
            transaction_type="expense", frequency="monthly",
            day_of_month=1, is_active=True
        ))
        db.add(RecurringTransaction(
            name="停用", amount=200, category="测试",
            transaction_type="expense", frequency="monthly",
            day_of_month=2, is_active=False
        ))
        db.commit()

        resp = client.get("/recurring?is_active=true")
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "活跃"

    def test_list_filter_type(self, db):
        """按收支类型筛选"""
        db.add(RecurringTransaction(
            name="收入", amount=100, category="工资",
            transaction_type="income", frequency="monthly",
            day_of_month=15, is_active=True
        ))
        db.add(RecurringTransaction(
            name="支出", amount=200, category="住房",
            transaction_type="expense", frequency="monthly",
            day_of_month=1, is_active=True
        ))
        db.commit()

        resp = client.get("/recurring?transaction_type=income")
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "收入"

    def test_get_single(self, db):
        """获取单条详情"""
        rt = RecurringTransaction(
            name="Netflix", amount=98, category="订阅",
            transaction_type="expense", frequency="monthly",
            day_of_month=10, is_active=True
        )
        db.add(rt)
        db.commit()

        resp = client.get(f"/recurring/{rt.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Netflix"

    def test_get_not_found(self):
        """不存在的ID返回404"""
        resp = client.get("/recurring/9999")
        assert resp.status_code == 404

    def test_update(self, db):
        """更新固定收支"""
        rt = RecurringTransaction(
            name="旧房租", amount=5000, category="住房",
            transaction_type="expense", frequency="monthly",
            day_of_month=1, is_active=True
        )
        db.add(rt)
        db.commit()

        resp = client.put(f"/recurring/{rt.id}", json={
            "name": "新房租",
            "amount": 6000,
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "新房租"
        assert resp.json()["amount"] == 6000

    def test_update_toggle_active(self, db):
        """启用/停用切换"""
        rt = RecurringTransaction(
            name="测试", amount=100, category="测试",
            transaction_type="expense", frequency="monthly",
            day_of_month=1, is_active=True
        )
        db.add(rt)
        db.commit()

        resp = client.put(f"/recurring/{rt.id}", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_delete(self, db):
        """删除固定收支"""
        rt = RecurringTransaction(
            name="测试", amount=100, category="测试",
            transaction_type="expense", frequency="monthly",
            day_of_month=1, is_active=True
        )
        db.add(rt)
        db.commit()

        resp = client.delete(f"/recurring/{rt.id}")
        assert resp.status_code == 200

        # 确认已删除
        resp = client.get(f"/recurring/{rt.id}")
        assert resp.status_code == 404

    def test_delete_not_found(self):
        """删除不存在的ID返回404"""
        resp = client.delete("/recurring/9999")
        assert resp.status_code == 404


class TestRecurringSummary:
    """固定收支汇总测试"""

    def test_empty_summary(self):
        """无记录时汇总为零"""
        resp = client.get("/recurring/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_monthly_income"] == 0
        assert data["total_monthly_expense"] == 0
        assert data["monthly_net"] == 0
        assert data["active_count"] == 0

    def test_summary_calculation(self, db):
        """汇总计算：月收入15000，月支出5000+98*4.33(weekly)"""
        db.add(RecurringTransaction(
            name="工资", amount=15000, category="工资",
            transaction_type="income", frequency="monthly",
            day_of_month=15, is_active=True
        ))
        db.add(RecurringTransaction(
            name="房租", amount=5000, category="住房",
            transaction_type="expense", frequency="monthly",
            day_of_month=1, is_active=True
        ))
        db.add(RecurringTransaction(
            name="健身", amount=98, category="健康",
            transaction_type="expense", frequency="weekly",
            day_of_month=1, is_active=True
        ))
        # 停用的不计入
        db.add(RecurringTransaction(
            name="已取消订阅", amount=50, category="订阅",
            transaction_type="expense", frequency="monthly",
            day_of_month=20, is_active=False
        ))
        db.commit()

        resp = client.get("/recurring/summary")
        data = resp.json()
        assert data["total_monthly_income"] == 15000
        assert data["total_monthly_expense"] > 5000  # 5000 + 98*4.33 ≈ 5424
        assert data["income_count"] == 1
        assert data["expense_count"] == 2  # 房租 + 健身
        assert data["active_count"] == 3  # 不包括停用的


class TestAutoDetect:
    """自动检测测试"""

    def test_auto_detect_empty(self):
        """无历史交易时检测为空"""
        resp = client.post("/recurring/auto-detect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["detected_count"] == 0

    def test_auto_detect_with_data(self, db):
        """有跨月重复交易时能检测到"""
        now = datetime.utcnow()
        # 模拟3个月的房租交易
        for month_offset in range(3):
            tx_date = now - timedelta(days=30 * month_offset)
            tx = Transaction(
                amount=5000,
                category="住房",
                account="招商银行卡",
                transaction_type="expense",
                parsed_at=tx_date.replace(day=1),
            )
            db.add(tx)
        db.commit()

        resp = client.post("/recurring/auto-detect?history_days=120")
        data = resp.json()
        assert data["detected_count"] >= 1
        detected = data["items"][0]
        assert detected["category"] == "住房"
        assert detected["transaction_type"] == "expense"
        assert abs(detected["amount"] - 5000) < 100

    def test_auto_detect_import(self, db):
        """检测并导入"""
        now = datetime.utcnow()
        for month_offset in range(2):
            tx_date = now - timedelta(days=30 * month_offset)
            tx = Transaction(
                amount=30, category="订阅", account="微信",
                transaction_type="expense",
                parsed_at=tx_date.replace(day=5),
            )
            db.add(tx)
        db.commit()

        resp = client.post("/recurring/auto-detect?history_days=90&import_detected=true")
        data = resp.json()
        assert data["imported_count"] >= 1

        # 验证已写入数据库
        resp = client.get("/recurring")
        items = resp.json()
        auto_items = [i for i in items if i["source"] == "auto"]
        assert len(auto_items) >= 1

    def test_auto_detect_no_duplicate_import(self, db):
        """重复导入应跳过"""
        now = datetime.utcnow()
        for month_offset in range(2):
            tx_date = now - timedelta(days=30 * month_offset)
            tx = Transaction(
                amount=5000, category="住房", account="招商银行卡",
                transaction_type="expense",
                parsed_at=tx_date.replace(day=1),
            )
            db.add(tx)
        db.commit()

        # 第一次导入
        resp = client.post("/recurring/auto-detect?history_days=90&import_detected=true")
        first_import = resp.json()["imported_count"]

        # 第二次导入应跳过
        resp = client.post("/recurring/auto-detect?history_days=90&import_detected=true")
        data = resp.json()
        assert data["skipped_count"] >= 1


class TestForecastIntegration:
    """与现金流预测集成测试"""

    def test_forecast_includes_user_recurring(self, db):
        """预测应包含用户定义的固定收支"""
        # 添加用户固定收支
        db.add(RecurringTransaction(
            name="工资", amount=15000, category="工资",
            transaction_type="income", frequency="monthly",
            day_of_month=15, is_active=True
        ))
        db.add(RecurringTransaction(
            name="房租", amount=5000, category="住房",
            transaction_type="expense", frequency="monthly",
            day_of_month=1, is_active=True
        ))
        db.commit()

        # 添加一些历史交易（让预测有基础数据）
        now = datetime.utcnow()
        for i in range(10):
            tx = Transaction(
                amount=50, category="餐饮", account="微信",
                transaction_type="expense",
                parsed_at=now - timedelta(days=i+1),
            )
            db.add(tx)
        db.commit()

        resp = client.get("/cashflow/forecast?days=30")
        data = resp.json()

        # 检查 recurring_items 包含用户定义的
        recurring = data["recurring_items"]
        names = [r.get("name", "") for r in recurring]
        assert "工资" in names or any(r["amount"] == 15000 for r in recurring)
        assert "房租" in names or any(r["amount"] == 5000 for r in recurring)

    def test_forecast_no_duplicate_with_auto(self, db):
        """用户定义的和自动检测的不重复"""
        now = datetime.utcnow()
        # 添加历史交易（会被自动检测）
        for month_offset in range(3):
            tx_date = now - timedelta(days=30 * month_offset)
            tx = Transaction(
                amount=5000, category="住房", account="招商银行卡",
                transaction_type="expense",
                parsed_at=tx_date.replace(day=1),
            )
            db.add(tx)
        # 添加用户定义（同分类+同日）
        db.add(RecurringTransaction(
            name="房租", amount=5000, category="住房",
            transaction_type="expense", frequency="monthly",
            day_of_month=1, is_active=True
        ))
        # 添加其他历史交易
        for i in range(5):
            tx = Transaction(
                amount=50, category="餐饮", account="微信",
                transaction_type="expense",
                parsed_at=now - timedelta(days=i+1),
            )
            db.add(tx)
        db.commit()

        resp = client.get("/cashflow/forecast?days=30&history_days=120")
        data = resp.json()

        # 检查1号的房租不重复出现
        day1_forecast = [d for d in data["daily_forecast"] if d["day"] == 1]
        if day1_forecast:
            # 房租应该只出现一次（5000，不是10000）
            assert day1_forecast[0]["recurring_expense"] <= 5500  # 5000 + 容差
