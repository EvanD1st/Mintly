"""Add observation-only reliability evidence without changing execution records."""
from alembic import op
import sqlalchemy as sa
revision='034_mint_opportunities'
down_revision='033_feed_automation'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('mint_opportunities',
        sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('wallet_id',sa.String(36),sa.ForeignKey('wallets.id'),nullable=False),
        sa.Column('drop_id',sa.String(64),sa.ForeignKey('drops.id'),nullable=False),
        sa.Column('chain_id',sa.Integer(),nullable=False),sa.Column('contract',sa.String(42),nullable=False),
        sa.Column('phase_id',sa.String(128),nullable=False),
        sa.Column('last_error_code',sa.String(40)),sa.Column('last_error_at',sa.DateTime(timezone=True)),
        *[sa.Column(n,sa.DateTime(timezone=True),nullable=False) for n in
            ('opens_at','closes_at','eligible_at','last_seen_at','created_at','updated_at')])
    op.create_index('ix_mint_opportunities_user_id','mint_opportunities',['user_id'])
    op.create_index('ix_mint_opportunities_opens_at','mint_opportunities',['opens_at'])


def downgrade():
    op.drop_table('mint_opportunities')
