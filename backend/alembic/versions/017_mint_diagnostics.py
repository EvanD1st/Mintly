"""Retain sanitized upstream response codes for every automatic mint attempt."""
from alembic import op
import sqlalchemy as sa
revision='017_mint_diagnostics'
down_revision='016_opensea_eligibility'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('mint_attempt_diagnostics',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('task_id',sa.String(36),sa.ForeignKey('mint_tasks.id',ondelete='CASCADE'),nullable=False),
        sa.Column('phase',sa.String(20),nullable=False),sa.Column('attempt_number',sa.Integer()),
        sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),sa.Column('finished_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('outcome',sa.String(40),nullable=False),sa.Column('signer_http_status',sa.Integer()),
        sa.Column('error_category',sa.String(40),nullable=False),sa.Column('upstream_events',sa.JSON(),nullable=False),
        sa.Column('next_retry_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_index('ix_mint_attempt_diagnostics_task_id','mint_attempt_diagnostics',['task_id'])

def downgrade():op.drop_table('mint_attempt_diagnostics')
