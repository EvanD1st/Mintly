"""Persistent public collection artwork metadata; no mint state changes."""
from alembic import op
import sqlalchemy as sa

revision = '024_collection_artwork'
down_revision = '023_native_currency_budgets'
branch_labels = depends_on = None


def upgrade():
    op.create_table('collection_artwork',
        sa.Column('key', sa.String(150), primary_key=True),
        sa.Column('collection_slug', sa.String(100), nullable=True),
        sa.Column('image_url', sa.String(2048), nullable=True),
        sa.Column('refresh_after', sa.DateTime(timezone=True), nullable=False),
        sa.Column('stale_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('collection_artwork')
