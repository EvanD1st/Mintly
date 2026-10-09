"""Durable per-event copy deferrals and outcomes."""
from alembic import op
import sqlalchemy as sa
revision='019_copy_event_retry'
down_revision='018_opensea_requests'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('copy_events',sa.Column('next_attempt_at',sa.DateTime(timezone=True)))
    op.add_column('copy_events',sa.Column('last_checked_at',sa.DateTime(timezone=True)))
    op.add_column('copy_events',sa.Column('last_error_category',sa.String(40)))
    op.add_column('copy_events',sa.Column('last_upstream_status',sa.Integer()))

def downgrade():
    for column in ('last_upstream_status','last_error_category','last_checked_at','next_attempt_at'):op.drop_column('copy_events',column)
