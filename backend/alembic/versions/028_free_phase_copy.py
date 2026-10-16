"""Free-phase wait metadata and account-scoped update notice acknowledgments."""
from alembic import op
import sqlalchemy as sa
revision = '028_free_phase_copy'
down_revision = '027_daily_list_notices'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('copy_events', sa.Column('phase_plan', sa.JSON(), nullable=True))
    op.add_column('users', sa.Column('feature_notices', sa.JSON(), nullable=False, server_default='{}'))


def downgrade():
    op.drop_column('users', 'feature_notices')
    op.drop_column('copy_events', 'phase_plan')
