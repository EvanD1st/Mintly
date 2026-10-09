"""Keep sanitized copy preparation failures and bounded retry attempts."""
from alembic import op
import sqlalchemy as sa
revision='020_copy_failure_reasons'
down_revision='019_copy_event_retry'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('copy_events',sa.Column('upstream_events',sa.JSON(),nullable=True))
    op.add_column('copy_events',sa.Column('preparation_attempts',sa.Integer(),nullable=False,server_default='0'))

def downgrade():
    op.drop_column('copy_events','preparation_attempts')
    op.drop_column('copy_events','upstream_events')
