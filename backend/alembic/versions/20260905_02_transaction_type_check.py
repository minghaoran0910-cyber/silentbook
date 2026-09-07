"""DB 层硬约束：transaction_type 只能是 income/expense；created_at 给库级默认值。

背景：外部写入方（OpenClaw 经 SSH 直写 PG 裸 SQL）绕过了 API 层校验，
'transfer' 等脏类型入库后导致整表查询 500。约束让非法写入当场失败，
而不是静默毒化数据。
"""
from alembic import op
import sqlalchemy as sa


revision = "20260905_02"
down_revision = "20260904_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # 1) 先把存量脏数据修成 expense（全为资金流出：投资/储蓄/自账户划转/还款）
    bind.execute(sa.text(
        "UPDATE transactions SET transaction_type = 'expense' "
        "WHERE transaction_type NOT IN ('income', 'expense')"
    ))
    # 2) CHECK 约束 + created_at 库级默认（batch 模式兼容 SQLite）
    with op.batch_alter_table("transactions") as batch:
        insp = sa.inspect(bind)
        try:
            checks = {c.get("name") for c in insp.get_check_constraints("transactions")}
        except Exception:
            checks = set()
        if "chk_transactions_type" not in checks:
            batch.create_check_constraint(
                "chk_transactions_type",
                "transaction_type IN ('income', 'expense')",
            )
        batch.alter_column("created_at", existing_type=sa.DateTime(),
                           server_default=sa.text("CURRENT_TIMESTAMP"),
                           existing_nullable=True)


def downgrade():
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("chk_transactions_type", type_="check")
        batch.alter_column("created_at", existing_type=sa.DateTime(),
                           server_default=None, existing_nullable=True)
