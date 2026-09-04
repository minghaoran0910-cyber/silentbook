"""Webhook 业务幂等列：webhook_events.body_hash + 唯一索引。

可重入：在 create_all 已建好列的新库上自动跳过；在存量库上补列。
SQLite 与 PostgreSQL 通用（plain ADD COLUMN 两边都支持）。
"""
from alembic import op
import sqlalchemy as sa

revision = "20260904_01"
down_revision = "20260717_02"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def _has_index(bind, name: str) -> bool:
    insp = sa.inspect(bind)
    try:
        for table in insp.get_table_names():
            for idx in insp.get_indexes(table):
                if idx.get("name") == name:
                    return True
    except Exception:
        pass
    return False


def upgrade():
    bind = op.get_bind()
    if not _has_column(bind, "webhook_events", "body_hash"):
        op.add_column("webhook_events", sa.Column("body_hash", sa.String(64), nullable=True))
    if not _has_index(bind, "uq_webhook_events_user_body"):
        op.create_index("uq_webhook_events_user_body", "webhook_events",
                        ["user_id", "body_hash"], unique=True)


def downgrade():
    bind = op.get_bind()
    if _has_index(bind, "uq_webhook_events_user_body"):
        op.drop_index("uq_webhook_events_user_body", table_name="webhook_events")
    if _has_column(bind, "webhook_events", "body_hash"):
        with op.batch_alter_table("webhook_events") as batch:
            batch.drop_column("body_hash")
