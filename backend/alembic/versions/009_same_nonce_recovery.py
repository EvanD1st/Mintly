"""Preserve original and replacement authorizations without replacing their history."""
from alembic import op
import sqlalchemy as sa
revision = '009_same_nonce_recovery'
down_revision = '008_plan_history'
branch_labels = depends_on = None


def upgrade():
    op.create_table('mint_recoveries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('mint_tasks.id'), nullable=False, unique=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('authorization_reference', sa.String(200), nullable=False),
        sa.Column('authorized_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempt_ceiling', sa.Integer(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('previous_hash', sa.String(66), nullable=False),
        sa.Column('previous_signed_tx_raw', sa.Text(), nullable=False),
        sa.Column('replacement_hash', sa.String(66)),
        sa.Column('replacement_signed_tx_raw', sa.Text()),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_mint_recoveries_user_id', 'mint_recoveries', ['user_id'])


def downgrade():
    op.drop_table('mint_recoveries')
