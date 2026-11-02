"""Add single-use account recovery codes without changing passwords or sessions."""
from alembic import op
import sqlalchemy as sa

revision = '032_account_recovery'
down_revision = '031_source_verification_retired'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('account_recovery_codes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('issued_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('code_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for column in ('user_id', 'issued_by', 'expires_at'):
        op.create_index(f'ix_account_recovery_codes_{column}', 'account_recovery_codes', [column])


def downgrade():
    op.drop_table('account_recovery_codes')
