"""
V2-025: 实时增量备份测试
"""
import os

from cryptography.fernet import Fernet

os.environ["WEBHOOK_SECRET"] = "test-shared-secret-0123456789abcdef"
os.environ["WEBHOOK_USER_ID"] = "1"
os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_backup_test.db"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"
os.environ.setdefault("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_mod
from app.main import app
from app.database import Base, get_db, Transaction, Account, Asset
import app.routers.backup as backup_mod
from app.backup_crypto import read_backup

main_mod.RATE_LIMIT_ENABLED = False

SQLALCHEMY_URL = "sqlite://"
engine = create_engine(
    SQLALCHEMY_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(scope="function")
def auth(tmp_path):
    Base.metadata.create_all(bind=engine)
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    # 隔离备份目录，避免 O_EXCL 文件名碰撞
    bdir = tmp_path / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    old_bdir = backup_mod.BACKUP_DIR
    backup_mod.BACKUP_DIR = bdir
    r = client.post(
        "/auth/register",
        json={"email": "backup@test.local", "password": "Testpass123"},
    )
    assert r.status_code in (200, 201), r.text
    j = r.json()
    token = j["access_token"]
    uid = j["user"]["id"]
    # 种子数据（带 user_id）
    db = TestingSessionLocal()
    try:
        db.add(Account(name="测试微信", account_type="wechat", purpose="consumption",
                       balance=1000.0, user_id=uid))
        for i in range(5):
            db.add(Transaction(amount=10.0 + i, category="餐饮", account="微信",
                               description=f"测试交易{i}", transaction_type="expense",
                               user_id=uid))
        db.add(Asset(name="测试资产", asset_type="cash", current_value=5000.0,
                     initial_value=5000.0, user_id=uid))
        db.commit()
    finally:
        db.close()
    yield {"headers": {"Authorization": f"Bearer {token}"}, "user_id": uid}
    Base.metadata.drop_all(bind=engine)
    backup_mod.BACKUP_DIR = old_bdir
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def _create(auth, qs="backup_type=full"):
    r = client.post(f"/backup/create?{qs}", headers=auth["headers"])
    return r


class TestBackupCreate:
    """测试创建备份"""

    def test_create_full_backup(self, auth):
        response = _create(auth, "backup_type=full")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "completed"
        assert data["backup_type"] == "full"
        assert data["record_count"] > 0
        assert data["file_size"] > 0
        assert data["duration_seconds"] >= 0
        assert "tables" in data
        assert "transactions" in data["tables"]

    def test_create_incremental_backup_first(self, auth):
        response = _create(auth, "backup_type=incremental")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "completed"
        assert data["backup_type"] == "incremental"
        assert data["record_count"] > 0
        assert data.get("since_checkpoint") is None

    def test_create_incremental_backup_second(self, auth):
        # 先做一次增量，建立 checkpoint
        r1 = _create(auth, "backup_type=incremental")
        assert r1.status_code == 200, r1.text
        # 再添加新数据
        db = TestingSessionLocal()
        try:
            db.add(Transaction(amount=99.9, category="购物", account="支付宝",
                               description="增量测试", transaction_type="expense",
                               user_id=auth["user_id"]))
            db.commit()
        finally:
            db.close()
        # 第二次增量应有 since_checkpoint
        response = _create(auth, "backup_type=incremental")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "completed"
        assert data.get("since_checkpoint") is not None

    def test_create_backup_specific_tables(self, auth):
        response = _create(auth, "backup_type=full&tables=transactions,assets")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "completed"
        assert "transactions" in data["tables"]
        assert "assets" in data["tables"]
        assert "liabilities" not in data["tables"]

    def test_create_backup_invalid_table(self, auth):
        response = _create(auth, "backup_type=full&tables=nonexistent")
        assert response.status_code == 400

    def test_create_backup_invalid_type(self, auth):
        response = _create(auth, "backup_type=invalid")
        assert response.status_code == 400 or response.status_code == 422


class TestBackupList:
    """测试列出备份"""

    def test_list_backups(self, auth):
        _create(auth, "backup_type=full")
        response = client.get("/backup/list", headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()
        assert "backups" in data
        assert "total" in data
        assert len(data["backups"]) > 0

    def test_list_backups_with_limit(self, auth):
        _create(auth, "backup_type=full")
        _create(auth, "backup_type=full")
        response = client.get("/backup/list?limit=2", headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data["backups"]) <= 2

    def test_list_backups_filter_status(self, auth):
        _create(auth, "backup_type=full")
        response = client.get("/backup/list?status=completed", headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()
        for backup in data["backups"]:
            assert backup["status"] == "completed"


class TestBackupStatus:
    """测试备份状态"""

    def test_get_backup_status(self, auth):
        _create(auth, "backup_type=full")
        response = client.get("/backup/status", headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()
        assert "last_backup" in data
        assert "total_backups" in data
        assert "total_backup_size" in data
        assert "backup_directory" in data
        assert data["total_backups"] > 0
        assert data["total_backup_size"] > 0


class TestBackupDetail:
    """测试备份详情"""

    def test_get_backup_detail(self, auth):
        _create(auth, "backup_type=full")
        list_response = client.get("/backup/list?limit=1", headers=auth["headers"])
        backup_id = list_response.json()["backups"][0]["id"]

        response = client.get(f"/backup/{backup_id}", headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["id"] == backup_id
        assert "preview" in data
        if data["preview"]:
            assert "metadata" in data["preview"]
            assert "table_names" in data["preview"]

    def test_get_backup_detail_not_found(self, auth):
        response = client.get("/backup/99999", headers=auth["headers"])
        assert response.status_code == 404


class TestBackupRestore:
    """测试备份恢复"""

    def test_restore_dry_run(self, auth):
        _create(auth, "backup_type=full")
        list_response = client.get("/backup/list?limit=1", headers=auth["headers"])
        backup_id = list_response.json()["backups"][0]["id"]

        response = client.post(f"/backup/restore?backup_id={backup_id}&dry_run=true",
                               headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "dry_run"
        assert "tables" in data
        for table_info in data["tables"].values():
            assert "backup_records" in table_info
            assert "current_records" in table_info
            assert table_info["action"] == "preview_only"

    def test_restore_actual(self, auth):
        _create(auth, "backup_type=full")
        list_response = client.get("/backup/list?limit=1", headers=auth["headers"])
        backup_id = list_response.json()["backups"][0]["id"]

        # 新版恢复需确认词 RESTORE-<id>
        response = client.post(
            f"/backup/restore?backup_id={backup_id}&dry_run=false&confirmation=RESTORE-{backup_id}",
            headers=auth["headers"])
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "restored"
        assert "message" in data

    def test_restore_not_found(self, auth):
        response = client.post("/backup/restore?backup_id=99999&dry_run=true",
                               headers=auth["headers"])
        assert response.status_code == 404


class TestBackupFileIntegrity:
    """测试备份文件完整性"""

    def test_backup_file_is_valid_gzip(self, auth):
        _create(auth, "backup_type=full")
        list_response = client.get("/backup/list?limit=1", headers=auth["headers"])
        backup = list_response.json()["backups"][0]
        file_path = backup["file_path"]

        assert os.path.exists(file_path)
        # 新版为加密备份，用 read_backup 解密读取
        from pathlib import Path
        data = read_backup(Path(file_path))
        assert "metadata" in data
        assert "tables" in data

    def test_backup_contains_expected_data(self, auth):
        _create(auth, "backup_type=full")
        list_response = client.get("/backup/list?limit=1", headers=auth["headers"])
        backup = list_response.json()["backups"][0]
        file_path = backup["file_path"]

        from pathlib import Path
        data = read_backup(Path(file_path))

        transactions = data["tables"].get("transactions", [])
        assert len(transactions) > 0
        for tx in transactions:
            assert "amount" in tx
            assert "category" in tx
            assert "transaction_type" in tx
