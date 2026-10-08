"""Persist per-receiving-wallet whitelist preferences without changing old consent."""
from alembic import op
import sqlalchemy as sa

revision = '013_copy_preferences'
down_revision = '012_wallet_unlink'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('copy_watches', sa.Column('preferences', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade():
    op.drop_column('copy_watches', 'preferences')
