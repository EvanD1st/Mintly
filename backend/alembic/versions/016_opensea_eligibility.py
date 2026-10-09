"""Isolated OpenSea eligibility consent and explicit stage selection."""
from alembic import op
import sqlalchemy as sa
revision='016_opensea_eligibility'
down_revision='015_mint_controls'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('opensea_access',
        sa.Column('wallet_id',sa.String(36),sa.ForeignKey('wallets.id'),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('terms_version',sa.String(64),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),sa.Column('consented_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_opensea_access_user_id','opensea_access',['user_id'])
    op.add_column('mint_plans',sa.Column('selected_stage',sa.JSON()))

def downgrade():
    op.drop_column('mint_plans','selected_stage')
    op.drop_table('opensea_access')
