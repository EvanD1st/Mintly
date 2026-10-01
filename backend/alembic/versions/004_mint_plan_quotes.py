"""Quantity and timestamped ETH/USDT cost snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "004_mint_plan_quotes"
down_revision = "003_opensea_mint_plans"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("mint_plans", sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("mint_plans", sa.Column("eth_usdt_rate", sa.String(40)))
    op.add_column("mint_plans", sa.Column("rate_checked_at", sa.DateTime(timezone=True)))

def downgrade():
    op.drop_column("mint_plans", "rate_checked_at")
    op.drop_column("mint_plans", "eth_usdt_rate")
    op.drop_column("mint_plans", "quantity")
