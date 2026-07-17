"""Add tenant ownership to existing SilentBook data.

Run once before deploying the user-isolation code:
    DATABASE_URL=... MIGRATION_OWNER_USER_ID=1 python -m migrations.add_user_isolation

The migration is transactional. Existing rows are assigned to the explicitly
configured owner; it never guesses when multiple users exist.
"""
import os

from sqlalchemy import create_engine, text


TABLES = (
    "transactions",
    "assets",
    "liabilities",
    "agent_configs",
    "settings",
    "accounts",
    "transfers",
    "analysis_results",
    "positions",
    "trade_records",
    "financial_goals",
    "goal_contributions",
    "recurring_transactions",
    "sync_logs",
    "backup_records",
)


def migrate() -> None:
    database_url = os.environ["DATABASE_URL"]
    owner = int(os.environ["MIGRATION_OWNER_USER_ID"])
    engine = create_engine(database_url)
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM users WHERE id = :owner AND is_active = true"),
            {"owner": owner},
        ).scalar()
        if not exists:
            raise RuntimeError(f"active migration owner user {owner} does not exist")

        for table in TABLES:
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS user_id INTEGER'))
            conn.execute(
                text(f'UPDATE "{table}" SET user_id = :owner WHERE user_id IS NULL'),
                {"owner": owner},
            )
            conn.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN user_id SET NOT NULL'))
            conn.execute(
                text(
                    f'CREATE INDEX IF NOT EXISTS ix_{table}_user_id '
                    f'ON "{table}" (user_id)'
                )
            )
            constraint = f"fk_{table}_user_id"
            has_constraint = conn.execute(
                text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
                {"name": constraint},
            ).scalar()
            if not has_constraint:
                conn.execute(
                    text(
                        f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint}" '
                        'FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE'
                    )
                )

        conn.execute(text("ALTER TABLE settings DROP CONSTRAINT IF EXISTS settings_key_key"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_settings_user_key "
                "ON settings (user_id, key)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS webhook_events ("
                "id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "event_id VARCHAR(128) NOT NULL, signature_timestamp INTEGER NOT NULL, "
                "received_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_webhook_events_user_id ON webhook_events(user_id)"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_events_user_event "
                "ON webhook_events(user_id, event_id)"
            )
        )


if __name__ == "__main__":
    migrate()
