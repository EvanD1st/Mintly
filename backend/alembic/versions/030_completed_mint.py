"""Public receipt evidence for a mint completed outside an unsigned task."""
from alembic import op
import sqlalchemy as sa

revision = '030_completed_mint'
down_revision = '029_two_source_feed'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('mint_tasks', sa.Column('external_mint', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('mint_tasks', 'external_mint')
