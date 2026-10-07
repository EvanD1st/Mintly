"""Retain unlinked wallets and stop further broadcasts without losing receipts."""
from alembic import op
import sqlalchemy as sa

revision = '012_wallet_unlink'
down_revision = '011_dismissed_drops'
branch_labels = depends_on = None


def upgrade():
    op.add_column('wallets', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mint_tasks', sa.Column('broadcast_disabled_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('mint_tasks', 'broadcast_disabled_at')
    op.drop_column('wallets', 'archived_at')
