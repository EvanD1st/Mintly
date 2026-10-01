"""Add the timestamp inherited by MintPermission from Base."""
from alembic import op
import sqlalchemy as sa

revision = '006_permission_updated_at'
down_revision = '005_mint_permissions'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'mint_permissions',
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text('UPDATE mint_permissions SET updated_at = created_at'))
    with op.batch_alter_table('mint_permissions') as batch:
        batch.alter_column(
            'updated_at', existing_type=sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        )


def downgrade():
    with op.batch_alter_table('mint_permissions') as batch:
        batch.drop_column('updated_at')
