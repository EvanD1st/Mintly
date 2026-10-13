"""Daily source identity and isolated wallet display cache."""
from alembic import op
import sqlalchemy as sa
revision='025_daily_feed'
down_revision='024_collection_artwork'
branch_labels=depends_on=None
def upgrade():
    op.add_column('source_posts',sa.Column('list_date',sa.Date(),nullable=True))
    op.add_column('source_posts',sa.Column('parser_version',sa.Integer(),nullable=False,server_default='0'))
    op.create_index('ix_source_posts_list_date','source_posts',['list_date'])
    op.create_table('feed_wallet_selections',
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),primary_key=True),
        sa.Column('wallet_id',sa.String(36),sa.ForeignKey('wallets.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for column in ('source_entry_key','source_price_text','source_time_text'):
        op.add_column('drops',sa.Column(column,sa.String({'source_entry_key':64,'source_price_text':200,'source_time_text':100}[column]),nullable=True))
    with op.batch_alter_table('drops') as batch:
        batch.create_unique_constraint('uq_drop_source_entry',['source_post_id','source_entry_key'])
    op.create_table('feed_wallet_checks',
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),primary_key=True),
        sa.Column('wallet_id',sa.String(36),sa.ForeignKey('wallets.id'),primary_key=True),
        sa.Column('drop_id',sa.String(64),sa.ForeignKey('drops.id'),primary_key=True),
        sa.Column('status',sa.String(24),nullable=False),sa.Column('result',sa.JSON(),nullable=False),
        *[sa.Column(k,sa.DateTime(timezone=True)) for k in ('checked_at','expires_at','next_attempt_at','lease_until')],
        sa.Column('attempts',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
def downgrade():
    op.drop_table('feed_wallet_selections')
    op.drop_table('feed_wallet_checks')
    with op.batch_alter_table('drops') as batch:
        batch.drop_constraint('uq_drop_source_entry',type_='unique')
        for c in ('source_entry_key','source_price_text','source_time_text'):batch.drop_column(c)
    op.drop_index('ix_source_posts_list_date',table_name='source_posts')
    op.drop_column('source_posts','parser_version');op.drop_column('source_posts','list_date')
