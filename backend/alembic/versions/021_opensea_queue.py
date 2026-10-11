"""Cross-process bounded OpenSea request queue; contains no credentials or payloads."""
from alembic import op
import sqlalchemy as sa
revision='021_opensea_queue'
down_revision='020_copy_failure_reasons'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('opensea_request_waiters',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('priority',sa.Integer(),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_index('ix_opensea_request_waiters_expires_at','opensea_request_waiters',['expires_at'])

def downgrade():op.drop_table('opensea_request_waiters')
