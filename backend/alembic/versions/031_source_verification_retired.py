"""Retain historical source evidence while retiring verification retries."""
from alembic import op
import sqlalchemy as sa

revision = '031_source_verification_retired'
down_revision = '030_completed_mint'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('source_posts', sa.Column('verification_retired_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('source_posts', 'verification_retired_at')
