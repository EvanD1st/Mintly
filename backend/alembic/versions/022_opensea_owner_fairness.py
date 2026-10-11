"""Alternate equally urgent OpenSea mint permits among account owners."""
from alembic import op
import sqlalchemy as sa

revision='022_opensea_owner_fairness'
down_revision='021_opensea_queue'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('opensea_request_gates',sa.Column('last_owner_id',sa.String(36),nullable=True))
    op.add_column('opensea_request_waiters',sa.Column('owner_id',sa.String(36),nullable=True))

def downgrade():
    op.drop_column('opensea_request_waiters','owner_id')
    op.drop_column('opensea_request_gates','last_owner_id')
