"""Durable automatic task authorization, grant budgets and nonce reservations."""
from alembic import op
import sqlalchemy as sa

revision = '007_automatic_execution'
down_revision = '006_permission_updated_at'
branch_labels = depends_on = None


def upgrade():
    op.create_table('automatic_grants',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('wallet_id', sa.String(36), sa.ForeignKey('wallets.id'), nullable=False),
        sa.Column('adapter', sa.String(40), nullable=False),
        sa.Column('chain_id', sa.Integer(), nullable=False),
        sa.Column('account', sa.String(42), nullable=False),
        sa.Column('context_hash', sa.String(64), unique=True, nullable=False),
        sa.Column('scope', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('budget_wei', sa.BigInteger(), nullable=False),
        sa.Column('reserved_wei', sa.BigInteger(), nullable=False),
        sa.Column('spent_wei', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    for name in ('user_id', 'wallet_id'):
        op.create_index(f'ix_automatic_grants_{name}', 'automatic_grants', [name])
    op.create_table('automatic_locks', sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('revision', sa.Integer(), nullable=False),
                    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
                    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.execute('INSERT INTO automatic_locks (id, revision) VALUES (1, 0)')
    with op.batch_alter_table('mint_authorizations') as batch:
        batch.add_column(sa.Column('snapshot', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('grant_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_authorization_grant', 'automatic_grants', ['grant_id'], ['id'])
    with op.batch_alter_table('mint_tasks') as batch:
        for name, typ in [('execution_mode', sa.String(40)), ('request_hash', sa.String(64)),
                          ('receipt_block_hash', sa.String(66)), ('next_attempt_at', sa.DateTime(timezone=True))]:
            batch.add_column(sa.Column(name, typ, nullable=True))
        batch.add_column(sa.Column('preparation_attempts', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('notification_pending', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_index('ix_mint_tasks_execution_mode', ['execution_mode'])
    op.create_table('automatic_nonces',
        sa.Column('task_id', sa.String(36), sa.ForeignKey('mint_tasks.id'), primary_key=True),
        sa.Column('chain_id', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(42), nullable=False),
        sa.Column('nonce', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('chain_id', 'address', 'nonce', name='uq_automatic_nonce'))


def downgrade():
    op.drop_table('automatic_nonces')
    with op.batch_alter_table('mint_tasks') as batch:
        batch.drop_index('ix_mint_tasks_execution_mode')
        for name in ('execution_mode','request_hash','receipt_block_hash','next_attempt_at','preparation_attempts','notification_pending'):
            batch.drop_column(name)
    with op.batch_alter_table('mint_authorizations') as batch:
        batch.drop_constraint('fk_authorization_grant', type_='foreignkey')
        batch.drop_column('grant_id')
        batch.drop_column('snapshot')
    op.drop_table('automatic_locks')
    op.drop_table('automatic_grants')
