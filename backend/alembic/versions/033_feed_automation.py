"""Standing free-list approvals and independently checked phase-opening tracking."""
from alembic import op
import sqlalchemy as sa
revision='033_feed_automation'
down_revision='032_account_recovery'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('mint_tasks',sa.Column('schedule_checked_at',sa.DateTime(timezone=True)))
    op.add_column('mint_tasks',sa.Column('schedule_note',sa.Text()))
    op.create_table('feed_mint_approvals',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('wallet_id',sa.String(36),sa.ForeignKey('wallets.id'),nullable=False),
        sa.Column('grant_id',sa.String(36),sa.ForeignKey('automatic_grants.id'),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),sa.Column('snapshot',sa.JSON(),nullable=False),
        sa.Column('context_hash',sa.String(64),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('last_checked_at',sa.DateTime(timezone=True)),sa.Column('note',sa.Text()))
    op.create_index('ix_feed_mint_approvals_user_id','feed_mint_approvals',['user_id'])
    op.create_index('ix_feed_mint_approvals_wallet_id','feed_mint_approvals',['wallet_id'])

def downgrade():
    op.drop_table('feed_mint_approvals')
    with op.batch_alter_table('mint_tasks') as batch:
        batch.drop_column('schedule_checked_at');batch.drop_column('schedule_note')
