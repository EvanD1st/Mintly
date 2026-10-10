"""Persist shared OpenSea pacing and cooldowns across workers/redeployments."""
from alembic import op
import sqlalchemy as sa
revision='018_opensea_requests'
down_revision='017_mint_diagnostics'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('opensea_request_gates',sa.Column('name',sa.String(24),primary_key=True),
        sa.Column('next_request_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('blocked_until',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))

def downgrade():op.drop_table('opensea_request_gates')
