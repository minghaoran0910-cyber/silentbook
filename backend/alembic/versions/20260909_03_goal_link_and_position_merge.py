"""联动改造：目标关联账户/资产 + 投资类资产合并为持仓。

1) financial_goals 新增 linked_account / linked_asset_id（可空，自动进度）。
2) 数据迁移：把用户在资产页直接建的 stock/fund/bond/gold 转成 positions 持仓
   （quantity=1 保值；黄金若 notes 里能解析出克数则按克数拆），并在 asset.notes
   写“关联持仓ID={id}”，之后同步链（sync_all_positions）接管现价更新。
   已是 [持仓] 双写或已有关联标记的行跳过。
"""
import re

from alembic import op
import sqlalchemy as sa


revision = "20260909_03"
down_revision = "20260905_02"
branch_labels = None
depends_on = None

TYPE_MAP = {"stock": "stock", "fund": "fund", "bond": "bond", "gold": "gold"}


def _parse_grams(notes):
    if not notes:
        return None
    m = re.search(r"克数[:：]\s*(\d+\.?\d*)", notes)
    if not m:
        m = re.search(r"(\d+\.?\d*)\s*[克g]", notes, re.IGNORECASE)
    if m:
        try:
            v = float(m.group(1))
            return v if v > 0 else None
        except ValueError:
            return None
    return None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()
    if "financial_goals" in tables:
        existing = {c["name"] for c in insp.get_columns("financial_goals")}
        with op.batch_alter_table("financial_goals") as batch:
            if "linked_account" not in existing:
                batch.add_column(sa.Column("linked_account", sa.String(100), nullable=True))
            if "linked_asset_id" not in existing:
                batch.add_column(sa.Column("linked_asset_id", sa.Integer(), nullable=True))

    # ---- 数据迁移：投资类资产 → 持仓 ----
    # 用 Core 直写：绕开 app.database 的租户全局钩子（do_orm_execute 会把
    # 未设租户的 Session 读全部过滤掉；before_flush 还会改写 user_id）。
    if not {"assets", "positions"} <= set(tables):
        return
    rows = bind.execute(
        sa.text(
            "SELECT id, name, asset_type, account, current_value, "
            "initial_value, currency, notes, user_id FROM assets "
            "WHERE asset_type IN ('stock','fund','bond','gold') "
            "AND status = 'active'"
        )
    ).fetchall()
    moved = 0
    for r in rows:
        _id, name, atype, account, cur, init, curr, notes, uid = r
        notes = notes or ""
        if "关联持仓ID" in notes or (name or "").startswith("[持仓]"):
            continue
        qty = 1.0
        if atype == "gold":
            grams = _parse_grams(notes)
            if grams:
                qty = grams
        cur_f = float(cur or 0)
        init_f = float(init or 0)
        res = bind.execute(
            sa.text(
                "INSERT INTO positions (name, symbol, position_type, quantity, "
                "avg_cost, current_price, currency, account, status, notes, "
                "created_at, updated_at, user_id) "
                "VALUES (:name, '', :ptype, :qty, :avg, :px, :curr, :account, "
                "'active', :notes, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :uid)"
            ),
            {
                "name": name,
                "ptype": TYPE_MAP[atype],
                "qty": qty,
                "avg": (init_f / qty) if qty else 0,
                "px": (cur_f / qty) if qty else 0,
                "curr": curr or "CNY",
                "account": account,
                "notes": f"从资产[{name}]合并迁移",
                "uid": uid,
            },
        )
        pos_id = res.lastrowid
        bind.execute(
            sa.text("UPDATE assets SET notes = :notes WHERE id = :id"),
            {"notes": (notes + f"\n关联持仓ID={pos_id}").strip(), "id": _id},
        )
        moved += 1
    print(f"linkage migration: {moved} investment assets moved to positions")


def downgrade():
    # 数据回滚：删除本次迁移建的持仓（资产行保留，关联标记需手动清理）
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "positions" in insp.get_table_names():
        bind.execute(
            sa.text("DELETE FROM positions WHERE notes LIKE '从资产[%]合并迁移%'")
        )
    if "financial_goals" in insp.get_table_names():
        existing = {c["name"] for c in insp.get_columns("financial_goals")}
        with op.batch_alter_table("financial_goals") as batch:
            if "linked_asset_id" in existing:
                batch.drop_column("linked_asset_id")
            if "linked_account" in existing:
                batch.drop_column("linked_account")
