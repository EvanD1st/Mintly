"""Separate copy section, retained observations and immutable rule approvals."""
from alembic import op
import sqlalchemy as sa

revision = '010_copy_mints'
down_revision = '009_same_nonce_recovery'
branch_labels = depends_on = None


def dates():
    return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table('copy_watches', sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('address', sa.String(42), nullable=False), sa.Column('label', sa.String(80), nullable=False),
        sa.Column('chains', sa.JSON(), nullable=False), sa.Column('cursors', sa.JSON(), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True)), *dates())
    op.create_index('ix_copy_watches_user_id', 'copy_watches', ['user_id'])
    op.create_table('copy_rules', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('watch_id', sa.String(64), sa.ForeignKey('copy_watches.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('grant_id', sa.String(36), sa.ForeignKey('automatic_grants.id'), nullable=False),
        sa.Column('chain_id', sa.Integer(), nullable=False), sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('context_hash', sa.String(64), nullable=False), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resume_after_block', sa.BigInteger(), nullable=False),
        sa.Column('budget_wei', sa.BigInteger(), nullable=False), sa.Column('reserved_wei', sa.BigInteger(), nullable=False),
        sa.Column('spent_wei', sa.BigInteger(), nullable=False), *dates())
    op.create_index('ix_copy_rules_watch_id', 'copy_rules', ['watch_id'])
    op.create_index('ix_copy_rules_user_id', 'copy_rules', ['user_id'])
    with op.batch_alter_table('mint_tasks') as batch:
        batch.add_column(sa.Column('copy_rule_id', sa.String(36)))
        batch.create_foreign_key('fk_mint_tasks_copy_rule', 'copy_rules', ['copy_rule_id'], ['id'])
        batch.add_column(sa.Column('copy_stage_key', sa.String(64)))
        batch.create_unique_constraint('uq_mint_tasks_copy_stage_key', ['copy_stage_key'])
    op.create_table('copy_events', sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('watch_id', sa.String(64), sa.ForeignKey('copy_watches.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('observation', sa.JSON(), nullable=False), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('note', sa.Text()), sa.Column('task_id', sa.String(36), sa.ForeignKey('mint_tasks.id'), unique=True), *dates())
    op.create_index('ix_copy_events_watch_id', 'copy_events', ['watch_id'])
    op.create_index('ix_copy_events_user_id', 'copy_events', ['user_id'])


def downgrade():
    op.drop_table('copy_events')
    with op.batch_alter_table('mint_tasks') as batch:
        batch.drop_constraint('fk_mint_tasks_copy_rule', type_='foreignkey')
        batch.drop_constraint('uq_mint_tasks_copy_stage_key', type_='unique')
        batch.drop_column('copy_stage_key')
        batch.drop_column('copy_rule_id')
    op.drop_table('copy_rules')
    op.drop_table('copy_watches')
