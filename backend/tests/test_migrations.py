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
    # 后续迁移会碰 transactions / financial_goals 表，这里一并建最小结构
    con.execute(
        "CREATE TABLE transactions ("
        "id INTEGER PRIMARY KEY, amount NUMERIC(18, 2) NOT NULL, "
        "category VARCHAR(50) NOT NULL, account VARCHAR(50) NOT NULL, "
        "description TEXT, transaction_type VARCHAR(20) NOT NULL, "
        "raw_text TEXT, confidence FLOAT, parsed_at DATETIME, "
        "created_at DATETIME, user_id INTEGER NOT NULL)"
    )
    con.execute(
        "CREATE TABLE financial_goals ("
        "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
        "goal_type VARCHAR(30) NOT NULL, target_amount NUMERIC(18, 2) NOT NULL, "
        "current_amount NUMERIC(18, 2) NOT NULL, currency VARCHAR(10), "
        "deadline DATE, priority VARCHAR(10), status VARCHAR(20), notes TEXT, "
        "created_at DATETIME, updated_at DATETIME, user_id INTEGER NOT NULL)"
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


def test_position_merge_migration():
    """20260909_03：资产页直建的股票转成持仓并写关联标记；目标表加关联列。"""
    from alembic.config import Config
    from alembic import command
    import sqlalchemy as sa

    DB2 = "/tmp/sb_mig_merge.db"
    if os.path.exists(DB2):
        os.remove(DB2)
    os.environ["DATABASE_URL"] = f"sqlite:///{DB2}"
    con = sqlite3.connect(DB2)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255))")
    con.execute("INSERT INTO users (id, email) VALUES (1, 'm@test.local')")
    con.execute(
        "CREATE TABLE financial_goals ("
        "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
        "goal_type VARCHAR(30) NOT NULL, target_amount NUMERIC(18,2) NOT NULL, "
        "current_amount NUMERIC(18,2) NOT NULL, currency VARCHAR(10), "
        "deadline DATE, priority VARCHAR(10), status VARCHAR(20), notes TEXT, "
        "created_at DATETIME, updated_at DATETIME, user_id INTEGER NOT NULL)"
    )
    con.execute(
        "CREATE TABLE assets ("
        "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
        "asset_type VARCHAR(30) NOT NULL, account VARCHAR(100), "
        "current_value NUMERIC(18,2) NOT NULL, initial_value NUMERIC(18,2), "
        "currency VARCHAR(10), liquidity VARCHAR(10), status VARCHAR(20), "
        "notes TEXT, created_at DATETIME, updated_at DATETIME, "
        "user_id INTEGER NOT NULL)"
    )
    con.execute(
        "CREATE TABLE positions ("
        "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, symbol VARCHAR(20), "
        "position_type VARCHAR(20) NOT NULL, quantity NUMERIC(18,4), "
        "avg_cost NUMERIC(18,4), current_price NUMERIC(18,4), currency VARCHAR(10), "
        "account VARCHAR(100), status VARCHAR(20), notes TEXT, "
        "created_at DATETIME, updated_at DATETIME, user_id INTEGER NOT NULL)"
    )
    # 一笔用户直建的股票资产 + 一笔已是持仓双写的（应跳过）
    con.execute(
        "INSERT INTO assets (name, asset_type, current_value, initial_value, "
        "status, user_id) VALUES "
        "('贵州茅台', 'stock', 10000, 8000, 'active', 1),"
        "('[持仓] 沪深300', 'fund', 5000, 5000, 'active', 1)"
    )
    con.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("INSERT INTO alembic_version VALUES ('20260905_02')")
    con.commit()
    con.close()
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    eng = sa.create_engine(f"sqlite:///{DB2}")
    with eng.connect() as c:
        pos = c.execute(sa.text(
            "SELECT position_type, quantity, avg_cost, current_price "
            "FROM positions WHERE name='贵州茅台'")).fetchall()
        assert len(pos) == 1, pos
        assert pos[0][0] == "stock" and pos[0][1] == 1
        assert pos[0][2] == 8000 and pos[0][3] == 10000
        note = c.execute(sa.text(
            "SELECT notes FROM assets WHERE name='贵州茅台'")).scalar()
        assert "关联持仓ID=" in note, note
        # [持仓] 双写行未被重复迁移
        assert c.execute(sa.text(
            "SELECT count(*) FROM positions WHERE name='[持仓] 沪深300'")).scalar() == 0
        # 目标表新列存在
        cols = [r[1] for r in c.execute(sa.text("PRAGMA table_info(financial_goals)"))]
        assert "linked_account" in cols and "linked_asset_id" in cols
