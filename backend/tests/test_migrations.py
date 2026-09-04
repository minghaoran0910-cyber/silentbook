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
