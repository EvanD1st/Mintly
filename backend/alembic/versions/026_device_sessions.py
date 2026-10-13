"""Add rotating device sessions without changing existing bearer sessions."""
from alembic import op
import sqlalchemy as sa
revision='026_device_sessions'
down_revision='025_daily_feed'
branch_labels=depends_on=None

def upgrade():
    op.create_table('device_sessions',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('origin',sa.String(250),nullable=False),sa.Column('token_hash',sa.String(64),unique=True,nullable=False),
        sa.Column('generation',sa.Integer(),nullable=False),
        *[sa.Column(k,sa.DateTime(timezone=True),nullable=False) for k in ('last_used_at','expires_at','access_expires_at','created_at','updated_at')],
        sa.Column('revoked_at',sa.DateTime(timezone=True)),sa.Column('rotated_at',sa.DateTime(timezone=True)),
        sa.Column('last_request_hash',sa.String(64)))
    op.create_index('ix_device_sessions_user_id','device_sessions',['user_id'])
    op.create_table('device_refresh_uses',sa.Column('token_hash',sa.String(64),primary_key=True),
        sa.Column('family_id',sa.String(36),sa.ForeignKey('device_sessions.id'),nullable=False),
        sa.Column('generation',sa.Integer(),nullable=False),
        *[sa.Column(k,sa.DateTime(timezone=True),nullable=False) for k in ('used_at','created_at','updated_at')])
    op.create_index('ix_device_refresh_uses_family_id','device_refresh_uses',['family_id'])
    with op.batch_alter_table('auth_sessions') as batch:
        batch.add_column(sa.Column('device_session_id',sa.String(36)))
        batch.create_foreign_key('fk_auth_device_session','device_sessions',['device_session_id'],['id'])
        batch.create_index('ix_auth_sessions_device_session_id',['device_session_id'])

def downgrade():
    with op.batch_alter_table('auth_sessions') as batch:
        batch.drop_index('ix_auth_sessions_device_session_id')
        batch.drop_constraint('fk_auth_device_session',type_='foreignkey')
        batch.drop_column('device_session_id')
    op.drop_table('device_refresh_uses');op.drop_table('device_sessions')
