"""Use exact numeric types for money and investment quantities."""
from alembic import op
import sqlalchemy as sa

revision = "20260717_02"
down_revision = None
branch_labels = None
depends_on = None

MONEY_COLUMNS = {
    "transactions": ["amount"], "assets": ["current_value", "initial_value"],
    "liabilities": ["total_amount", "current_amount", "monthly_payment", "min_payment"],
    "accounts": ["balance", "target_balance"], "transfers": ["amount"],
    "trade_records": ["amount", "fee"], "financial_goals": ["target_amount", "current_amount"],
    "goal_contributions": ["amount"], "recurring_transactions": ["amount"],
}
QUANTITY_COLUMNS = {"positions": ["quantity", "avg_cost", "current_price"], "trade_records": ["quantity", "price"]}

def _alter(mapping, column_type, scale=None):
    for table, columns in mapping.items():
        for column in columns:
            using = f"round({column}::numeric, {scale})" if scale is not None else f"{column}::double precision"
            op.alter_column(table, column, type_=column_type, postgresql_using=using)

def upgrade():
    _alter(MONEY_COLUMNS, sa.Numeric(18, 2), 2)
    _alter(QUANTITY_COLUMNS, sa.Numeric(24, 8), 8)
    op.create_index("ix_transactions_user_parsed_type", "transactions", ["user_id", "parsed_at", "transaction_type"], unique=False)
    op.create_index("ix_transactions_user_parsed_category", "transactions", ["user_id", "parsed_at", "category"], unique=False)

def downgrade():
    op.drop_index("ix_transactions_user_parsed_category", table_name="transactions")
    op.drop_index("ix_transactions_user_parsed_type", table_name="transactions")
    _alter(QUANTITY_COLUMNS, sa.Float())
    _alter(MONEY_COLUMNS, sa.Float())
