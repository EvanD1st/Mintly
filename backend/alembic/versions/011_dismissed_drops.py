"""Keep Today removals scoped to the user without deleting shared mint records."""
from alembic import op
import sqlalchemy as sa

revision = '011_dismissed_drops'
down_revision = '010_copy_mints'
branch_labels = depends_on = None


def upgrade():
    op.create_table('dismissed_drops',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('drop_id', sa.String(64), sa.ForeignKey('drops.id'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('dismissed_drops')
