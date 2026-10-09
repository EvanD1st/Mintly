"""Progress evidence, WAT daily budget, check-only copying and alert outbox."""
from alembic import op
import sqlalchemy as sa

revision = '015_mint_controls'
down_revision = '014_automation_readiness'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('daily_limit_wei', sa.BigInteger()))
    op.add_column('users', sa.Column('daily_limit_revision', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('daily_limit_status', sa.String(24), nullable=False, server_default='active'))
    for name in ('preparation_started_at','included_at','inclusion_observed_at'):
        op.add_column('mint_tasks', sa.Column(name, sa.DateTime(timezone=True)))
    op.add_column('mint_tasks', sa.Column('included_block_hash', sa.String(66)))
    op.add_column('mint_tasks', sa.Column('inclusion_result', sa.String(16)))
    timestamps = lambda: [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
                         sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)]
    op.create_table('daily_debits', sa.Column('task_id', sa.String(36), sa.ForeignKey('mint_tasks.id'), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False), sa.Column('day', sa.String(10), nullable=False),
        sa.Column('maximum_wei', sa.BigInteger(), nullable=False), sa.Column('actual_wei', sa.BigInteger()), *timestamps())
    op.create_index('ix_daily_debits_user_id','daily_debits',['user_id'])
    op.create_index('ix_daily_debits_day','daily_debits',['day'])
    op.create_table('copy_checks', sa.Column('watch_id', sa.String(64), sa.ForeignKey('copy_watches.id'), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('wallet_id', sa.String(36), sa.ForeignKey('wallets.id'), nullable=False),
        sa.Column('version', sa.String(64), nullable=False), sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False), sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False), *timestamps())
    op.create_index('ix_copy_checks_user_id','copy_checks',['user_id'])
    op.create_table('copy_check_results', sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('watch_id', sa.String(64), sa.ForeignKey('copy_watches.id'), nullable=False),
        sa.Column('wallet_id', sa.String(36), sa.ForeignKey('wallets.id'), nullable=False),
        sa.Column('event_id', sa.String(64), sa.ForeignKey('copy_events.id'), nullable=False),
        sa.Column('version', sa.String(64), nullable=False), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('note', sa.Text(), nullable=False), sa.Column('quantity', sa.Integer()), sa.Column('estimated_fee_wei', sa.BigInteger()), *timestamps())
    op.create_index('ix_copy_check_results_user_id','copy_check_results',['user_id'])
    op.create_table('wallet_alerts', sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('wallet_id', sa.String(36), sa.ForeignKey('wallets.id'), nullable=False),
        sa.Column('chain_id', sa.Integer(), nullable=False), sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('pending', sa.Boolean(), nullable=False),
        sa.Column('title', sa.String(120), nullable=False), sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True)), sa.Column('sent_at', sa.DateTime(timezone=True)), *timestamps())
    op.create_index('ix_wallet_alerts_user_id','wallet_alerts',['user_id'])


def downgrade():
    for table in ('wallet_alerts','copy_check_results','copy_checks','daily_debits'):
        op.drop_table(table)
    for name in ('inclusion_result','included_block_hash','inclusion_observed_at','included_at','preparation_started_at'):
        op.drop_column('mint_tasks',name)
    for name in ('daily_limit_status','daily_limit_revision','daily_limit_wei'):
        op.drop_column('users',name)
