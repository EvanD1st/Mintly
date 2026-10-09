"""Account-wide stop control and unsigned advance-check metadata."""
from alembic import op
import sqlalchemy as sa

revision = '014_automation_readiness'
down_revision = '013_copy_preferences'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('automation_paused', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('mint_tasks', sa.Column('preflight_checked_at', sa.DateTime(timezone=True)))
    op.add_column('mint_tasks', sa.Column('preflight_note', sa.Text()))


def downgrade():
    op.drop_column('mint_tasks', 'preflight_note')
    op.drop_column('mint_tasks', 'preflight_checked_at')
    op.drop_column('users', 'automation_paused')
