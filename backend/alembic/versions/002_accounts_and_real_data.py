"""Add per-user accounts and remove the reference demo records.

Revision ID: 002_accounts_real_data
Revises: 001_initial_schema
"""

from alembic import op
import sqlalchemy as sa

revision = "002_accounts_real_data"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username_hash", sa.String(64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_login_attempts_username_hash", "login_attempts", ["username_hash"])
    op.create_table(
        "wallet_pairings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("challenge_address", sa.String(42)),
        sa.Column("challenge_message", sa.Text()),
        sa.Column("linked_wallet_id", sa.String(36), sa.ForeignKey("wallets.id")),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_wallet_pairings_user_id", "wallet_pairings", ["user_id"])
    op.create_index("ix_wallet_pairings_code_hash", "wallet_pairings", ["code_hash"], unique=True)
    op.add_column("wallets", sa.Column("user_id", sa.String(36), *([] if sqlite else [sa.ForeignKey("users.id")])))
    op.create_index("ix_wallets_user_id", "wallets", ["user_id"])
    op.add_column("activity_events", sa.Column("user_id", sa.String(36), *([] if sqlite else [sa.ForeignKey("users.id")])))
    op.create_index("ix_activity_events_user_id", "activity_events", ["user_id"])
    op.add_column("notification_devices", sa.Column("user_id", sa.String(36), *([] if sqlite else [sa.ForeignKey("users.id")])))
    op.create_index("ix_notification_devices_user_id", "notification_devices", ["user_id"])

    # Old sample records must not be served to real users or executed by the worker.
    op.execute("DELETE FROM mint_tasks WHERE is_demo = true OR wallet_id IN (SELECT id FROM wallets WHERE is_demo = true) OR drop_id IN (SELECT id FROM drops WHERE is_demo = true)")
    op.execute("DELETE FROM mint_authorizations WHERE wallet_id IN (SELECT id FROM wallets WHERE is_demo = true) OR drop_id IN (SELECT id FROM drops WHERE is_demo = true)")
    op.execute("DELETE FROM mint_stages WHERE drop_id IN (SELECT id FROM drops WHERE is_demo = true)")
    op.execute("DELETE FROM drops WHERE is_demo = true")
    op.execute("DELETE FROM wallets WHERE is_demo = true")
    op.execute("DELETE FROM activity_events WHERE is_demo = true")
    op.execute("DELETE FROM source_connections WHERE source_name <> 'opensea'")
    op.execute("UPDATE mint_stages SET eligibility_status = 'unknown', eligibility_checked_at = NULL, eligibility_wallet_address = NULL, eligibility_evidence = NULL")
    op.execute("UPDATE drops SET status_label = 'Unverified', status_kind = 'unknown', is_supported_integration = false WHERE is_demo = false")
    op.execute("UPDATE notification_devices SET is_active = false WHERE user_id IS NULL")


def downgrade() -> None:
    op.drop_index("ix_notification_devices_user_id", "notification_devices")
    op.drop_column("notification_devices", "user_id")
    op.drop_index("ix_activity_events_user_id", "activity_events")
    op.drop_column("activity_events", "user_id")
    op.drop_index("ix_wallets_user_id", "wallets")
    op.drop_column("wallets", "user_id")
    op.drop_table("wallet_pairings")
    op.drop_table("login_attempts")
    op.drop_table("auth_sessions")
    op.drop_table("users")
