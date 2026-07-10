"""
V2-025: 实时增量备份测试
测试覆盖：
1. 创建全量备份
2. 创建增量备份
3. 列出备份记录
4. 获取备份状态
5. 获取备份详情
6. 恢复预览（dry_run）
7. 实际恢复
8. 错误处理
"""
import pytest
import json
import gzip
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 测试用备份目录
TEST_BACKUP_DIR = "/tmp/silentbook-test-backups"


@pytest.fixture(scope="module")
def setup_backup_env():
    """设置测试环境"""
    os.environ["BACKUP_DIR"] = TEST_BACKUP_DIR
    # 清理测试目录
    if os.path.exists(TEST_BACKUP_DIR):
        shutil.rmtree(TEST_BACKUP_DIR)
    os.makedirs(TEST_BACKUP_DIR, exist_ok=True)
    yield
    # 清理
    if os.path.exists(TEST_BACKUP_DIR):
        shutil.rmtree(TEST_BACKUP_DIR)


@pytest.fixture(scope="module")
def client(setup_backup_env):
    """创建测试客户端"""
    # 使用测试数据库
    test_db = "sqlite:///./test_backup.db"
    os.environ["DATABASE_URL"] = test_db

    # 重新导入以使用测试配置
    import importlib
    import sys

    # 清除缓存
    for mod in list(sys.modules.keys()):
        if "backend.app" in mod:
            del sys.modules[mod]

    from backend.app.database import engine, Base, SessionLocal, Transaction, Account, Asset
    Base.metadata.create_all(bind=engine)

    from backend.app.main import app, BACKUP_TABLES
    # 更新备份目录
    import backend.app.main as main_module
    main_module.BACKUP_DIR = Path(TEST_BACKUP_DIR)

    # 插入测试数据
    db = SessionLocal()
    try:
        # 清理旧数据
        db.query(Transaction).delete()
        db.query(Account).delete()
        db.query(Asset).delete()
        db.commit()

        # 创建测试账户
        account = Account(
            name="测试微信",
            account_type="wechat",
            purpose="consumption",
            balance=1000.0,
        )
        db.add(account)

        # 创建测试交易
        for i in range(5):
            tx = Transaction(
                amount=10.0 + i,
                category="餐饮",
                account="微信",
                description=f"测试交易{i}",
                transaction_type="expense",
            )
            db.add(tx)

        # 创建测试资产
        asset = Asset(
            name="测试资产",
            asset_type="cash",
            current_value=5000.0,
        )
        db.add(asset)
        db.commit()
    finally:
        db.close()

    with TestClient(app) as c:
        yield c


class TestBackupCreate:
    """测试创建备份"""

    def test_create_full_backup(self, client):
        """测试创建全量备份"""
        response = client.post("/backup/create?backup_type=full")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["backup_type"] == "full"
        assert data["record_count"] > 0
        assert data["file_size"] > 0
        assert data["duration_seconds"] >= 0
        assert "tables" in data
        assert "transactions" in data["tables"]

    def test_create_incremental_backup_first(self, client):
        """测试首次增量备份（等同于全量）"""
        response = client.post("/backup/create?backup_type=incremental")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["backup_type"] == "incremental"
        assert data["record_count"] > 0
        # 首次增量应该没有 since_checkpoint
        assert data.get("since_checkpoint") is None

    def test_create_incremental_backup_second(self, client):
        """测试第二次增量备份"""
        # 先添加新数据
        from backend.app.database import SessionLocal, Transaction
        db = SessionLocal()
        tx = Transaction(
            amount=99.9,
            category="购物",
            account="支付宝",
            description="增量测试",
            transaction_type="expense",
        )
        db.add(tx)
        db.commit()
        db.close()

        # 创建增量备份
        response = client.post("/backup/create?backup_type=incremental")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        # 第二次增量应该有 since_checkpoint
        assert data.get("since_checkpoint") is not None

    def test_create_backup_specific_tables(self, client):
        """测试只备份指定表"""
        response = client.post("/backup/create?backup_type=full&tables=transactions,assets")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "transactions" in data["tables"]
        assert "assets" in data["tables"]
        # 不应该包含未指定的表
        assert "liabilities" not in data["tables"]

    def test_create_backup_invalid_table(self, client):
        """测试备份不存在的表"""
        response = client.post("/backup/create?backup_type=full&tables=nonexistent")
        assert response.status_code == 400

    def test_create_backup_invalid_type(self, client):
        """测试无效的备份类型"""
        response = client.post("/backup/create?backup_type=invalid")
        assert response.status_code == 400 or response.status_code == 422


class TestBackupList:
    """测试列出备份"""

    def test_list_backups(self, client):
        """测试列出所有备份"""
        response = client.get("/backup/list")
        assert response.status_code == 200
        data = response.json()
        assert "backups" in data
        assert "total" in data
        assert len(data["backups"]) > 0

    def test_list_backups_with_limit(self, client):
        """测试限制返回数量"""
        response = client.get("/backup/list?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["backups"]) <= 2

    def test_list_backups_filter_status(self, client):
        """测试按状态过滤"""
        response = client.get("/backup/list?status=completed")
        assert response.status_code == 200
        data = response.json()
        for backup in data["backups"]:
            assert backup["status"] == "completed"


class TestBackupStatus:
    """测试备份状态"""

    def test_get_backup_status(self, client):
        """测试获取备份状态"""
        response = client.get("/backup/status")
        assert response.status_code == 200
        data = response.json()
        assert "last_backup" in data
        assert "total_backups" in data
        assert "total_backup_size" in data
        assert "backup_directory" in data
        assert data["total_backups"] > 0
        assert data["total_backup_size"] > 0


class TestBackupDetail:
    """测试备份详情"""

    def test_get_backup_detail(self, client):
        """测试获取备份详情"""
        # 先获取备份列表
        list_response = client.get("/backup/list?limit=1")
        backup_id = list_response.json()["backups"][0]["id"]

        # 获取详情
        response = client.get(f"/backup/{backup_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == backup_id
        assert "preview" in data
        if data["preview"]:
            assert "metadata" in data["preview"]
            assert "table_names" in data["preview"]

    def test_get_backup_detail_not_found(self, client):
        """测试获取不存在的备份"""
        response = client.get("/backup/99999")
        assert response.status_code == 404


class TestBackupRestore:
    """测试备份恢复"""

    def test_restore_dry_run(self, client):
        """测试恢复预览（dry_run）"""
        # 先获取备份列表
        list_response = client.get("/backup/list?limit=1")
        backup_id = list_response.json()["backups"][0]["id"]

        # 预览恢复
        response = client.post(f"/backup/restore?backup_id={backup_id}&dry_run=true")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "dry_run"
        assert "tables" in data
        for table_info in data["tables"].values():
            assert "backup_records" in table_info
            assert "current_records" in table_info
            assert table_info["action"] == "preview_only"

    def test_restore_actual(self, client):
        """测试实际恢复"""
        # 先获取备份列表
        list_response = client.get("/backup/list?limit=1")
        backup_id = list_response.json()["backups"][0]["id"]

        # 实际恢复
        response = client.post(f"/backup/restore?backup_id={backup_id}&dry_run=false")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "restored"
        assert "message" in data

    def test_restore_not_found(self, client):
        """测试恢复不存在的备份"""
        response = client.post("/backup/restore?backup_id=99999&dry_run=true")
        assert response.status_code == 404


class TestBackupFileIntegrity:
    """测试备份文件完整性"""

    def test_backup_file_is_valid_gzip(self, client):
        """测试备份文件是有效的 gzip 格式"""
        list_response = client.get("/backup/list?limit=1")
        backup = list_response.json()["backups"][0]
        file_path = backup["file_path"]

        assert os.path.exists(file_path)
        with gzip.open(file_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        assert "metadata" in data
        assert "tables" in data

    def test_backup_contains_expected_data(self, client):
        """测试备份包含预期数据"""
        list_response = client.get("/backup/list?limit=1")
        backup = list_response.json()["backups"][0]
        file_path = backup["file_path"]

        with gzip.open(file_path, "rt", encoding="utf-8") as f:
            data = json.load(f)

        # 检查交易数据
        transactions = data["tables"].get("transactions", [])
        assert len(transactions) > 0
        # 每条交易应有必要字段
        for tx in transactions:
            assert "amount" in tx
            assert "category" in tx
            assert "transaction_type" in tx
