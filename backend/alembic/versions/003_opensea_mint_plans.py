"""Private OpenSea mint plans for linked wallets.

Revision ID: 003_opensea_mint_plans
Revises: 002_accounts_real_data
"""

from alembic import op
import sqlalchemy as sa

revision = "003_opensea_mint_plans"
down_revision = "002_accounts_real_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mint_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("wallet_id", sa.String(36), sa.ForeignKey("wallets.id"), nullable=False),
        sa.Column("collection_slug", sa.String(100), nullable=False),
        sa.Column("collection_name", sa.String(150), nullable=False),
        sa.Column("chain", sa.String(20), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("contract_address", sa.String(42), nullable=False),
        sa.Column("opensea_url", sa.Text(), nullable=False),
        sa.Column("stage_uuid", sa.String(100)),
        sa.Column("stage_name", sa.String(80)),
        sa.Column("stage_type", sa.String(40)),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("price_wei", sa.BigInteger()),
        sa.Column("mint_value_wei", sa.BigInteger()),
        sa.Column("estimated_network_fee_wei", sa.BigInteger()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("status_note", sa.Text(), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("notified_stage_uuid", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("wallet_id", "collection_slug", name="uq_mint_plan_wallet_slug"),
    )
    op.create_index("ix_mint_plans_user_id", "mint_plans", ["user_id"])
    op.create_index("ix_mint_plans_wallet_id", "mint_plans", ["wallet_id"])
    op.create_index("ix_mint_plans_next_check", "mint_plans", ["next_check_at"])


def downgrade() -> None:
    op.drop_index("ix_mint_plans_next_check", "mint_plans")
    op.drop_index("ix_mint_plans_wallet_id", "mint_plans")
    op.drop_index("ix_mint_plans_user_id", "mint_plans")
    op.drop_table("mint_plans")
