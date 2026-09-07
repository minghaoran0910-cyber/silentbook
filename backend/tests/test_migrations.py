"""Alembic 迁移链测试：在缺 body_hash 列的存量库上 upgrade head 能补上。"""
import os
import sqlite3

os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef-test"

DB = "/tmp/sb_mig_chain.db"


def _legacy_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.execute(
        "CREATE TABLE webhook_events ("
        "id INTEGER PRIMARY KEY, event_id VARCHAR(128) NOT NULL, "
        "user_id INTEGER NOT NULL, "
        "signature_timestamp INTEGER NOT NULL, "
        "received_at DATETIME NOT NULL)"
    )
    con.execute(
        "CREATE UNIQUE INDEX uq_webhook_events_user_event "
        "ON webhook_events (user_id, event_id)"
    )
    # 后续迁移会碰 transactions 表，这里一并建最小结构
    con.execute(
        "CREATE TABLE transactions ("
        "id INTEGER PRIMARY KEY, amount NUMERIC(18, 2) NOT NULL, "
        "category VARCHAR(50) NOT NULL, account VARCHAR(50) NOT NULL, "
        "description TEXT, transaction_type VARCHAR(20) NOT NULL, "
        "raw_text TEXT, confidence FLOAT, parsed_at DATETIME, "
        "created_at DATETIME, user_id INTEGER NOT NULL)"
    )
    # alembic 版本表指向旧 revision，模拟“跑过 20260717_02 的存量库”
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("INSERT INTO alembic_version VALUES ('20260717_02')")
    con.commit()
    con.close()


def test_upgrade_adds_body_hash():
    _legacy_db()
    os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
    from alembic.config import Config
    from alembic import command

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    con = sqlite3.connect(DB)
    cols = [r[1] for r in con.execute("PRAGMA table_info(webhook_events)").fetchall()]
    idx = [r[1] for r in con.execute("PRAGMA index_list(webhook_events)").fetchall()]
    con.close()
    assert "body_hash" in cols
    assert "uq_webhook_events_user_body" in idx


def test_upgrade_idempotent_on_fresh():
    from app.database import Base, engine

    Base.metadata.create_all(bind=engine)
    os.environ["DATABASE_URL"] = str(engine.url)
    from alembic.config import Config
    from alembic import command

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")  # 新库重复跑必须不炸
    command.upgrade(cfg, "head")


def test_type_check_rejects_dirty_and_repairs():
    from alembic.config import Config
    from alembic import command
    import sqlalchemy as sa

    os.environ["DATABASE_URL"] = "sqlite:////tmp/sb_mig_type.db"
    if os.path.exists("/tmp/sb_mig_type.db"):
        os.remove("/tmp/sb_mig_type.db")
    cfg = Config("alembic.ini")
    # 先建出现代模型的表结构（模拟已跑过之前迁移的库）
    from app.database import Base
    eng = sa.create_engine("sqlite:////tmp/sb_mig_type.db")
    Base.metadata.create_all(bind=eng)
    # 塞一条脏数据（绕过 ORM，如外部裸 SQL）
    with eng.begin() as c:
        c.execute(sa.text(
            "INSERT INTO transactions (amount, category, account, "
            "transaction_type, user_id) "
            "VALUES (10, '储蓄', '招商银行', 'transfer', 1)"))
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        # 存量已修复
        assert c.execute(sa.text(
            "SELECT count(*) FROM transactions "
            "WHERE transaction_type NOT IN ('income','expense')")).scalar() == 0
        # 新脏数据被 CHECK 挡掉
        import pytest as _pt
        with _pt.raises(Exception):
            with eng.begin() as c2:
                c2.execute(sa.text(
                    "INSERT INTO transactions (amount, category, account, "
                    "transaction_type, user_id) "
                    "VALUES (10, '储蓄', '招商银行', 'transfer', 1)"))
        # 裸插入不带 created_at 也能落库（库级默认）
        c.execute(sa.text(
            "INSERT INTO transactions (amount, category, account, "
            "transaction_type, user_id) "
            "VALUES (10, '餐饮', '现金', 'expense', 1)"))
        assert c.execute(sa.text(
            "SELECT created_at IS NOT NULL FROM transactions "
            "WHERE category='餐饮'")).scalar() == 1
