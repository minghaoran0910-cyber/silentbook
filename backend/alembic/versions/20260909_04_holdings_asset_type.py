"""修复持仓双写资产的类型：wealth_mgmt/gold 曾被写成 other。

把 name 以 [持仓] 开头且 asset_type='other' 的行，按 notes 里“关联持仓ID=N”
找回 positions.position_type 映射回写（gold→gold、wealth_mgmt→wealth_mgmt）。
Core 直写，绕开租户钩子。
"""
import re

from alembic import op
import sqlalchemy as sa


revision = "20260909_04"
down_revision = "20260909_03"
branch_labels = None
depends_on = None

TYPE_MAP = {"stock": "stock", "fund": "fund", "bond": "bond",
            "gold": "gold", "wealth_mgmt": "wealth_mgmt", "other": "other"}


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if not {"assets", "positions"} <= tables:
        return
    rows = bind.execute(
        sa.text(
            "SELECT id, notes FROM assets "
            "WHERE name LIKE '[持仓] %' AND asset_type = 'other'"
        )
    ).fetchall()
    fixed = 0
    for aid, notes in rows:
        m = re.search(r"关联持仓ID=(\d+)", notes or "")
        if not m:
            continue
        ptype = bind.execute(
            sa.text("SELECT position_type FROM positions WHERE id = :pid"),
            {"pid": int(m.group(1))},
        ).scalar()
        if ptype in TYPE_MAP and TYPE_MAP[ptype] != "other":
            bind.execute(
                sa.text("UPDATE assets SET asset_type = :t WHERE id = :id"),
                {"t": TYPE_MAP[ptype], "id": aid},
            )
            fixed += 1
    print(f"holdings type fix: {fixed} rows")


def downgrade():
    pass  # 类型修正不可逆，无需回滚
