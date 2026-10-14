"""Durable per-account/device notices for lists visible on Today."""
from alembic import op
import sqlalchemy as sa
revision='027_daily_list_notices'
down_revision='026_device_sessions'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('daily_list_notices',
        sa.Column('id',sa.String(64),primary_key=True),sa.Column('list_date',sa.Date(),nullable=False),
        sa.Column('device_id',sa.String(36),sa.ForeignKey('notification_devices.id'),nullable=False),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('source_post_id',sa.String(36),sa.ForeignKey('source_posts.id'),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),sa.Column('attempts',sa.Integer(),nullable=False),
        sa.Column('next_attempt_at',sa.DateTime(timezone=True),nullable=False),
        *[sa.Column(k,sa.DateTime(timezone=True)) for k in ('lease_until','sent_at')],
        *[sa.Column(k,sa.DateTime(timezone=True),nullable=False) for k in ('created_at','updated_at')],
        sa.UniqueConstraint('list_date','device_id','user_id',name='uq_daily_notice_owner_device'))
    op.create_index('ix_daily_list_notices_list_date','daily_list_notices',['list_date'])

def downgrade():op.drop_table('daily_list_notices')
