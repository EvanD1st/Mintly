"""Durable two-source discovery with stable collection identities."""
from alembic import op
import sqlalchemy as sa
import hashlib
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

revision = '029_two_source_feed'
down_revision = '028_free_phase_copy'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('source_connections', sa.Column('next_attempt_at', sa.DateTime(timezone=True)))
    op.add_column('source_connections', sa.Column('catchup_cursor', sa.Text()))
    op.add_column('source_connections', sa.Column('catchup_until', sa.DateTime(timezone=True)))
    for name, kind in [('expanded_text',sa.Text()),('content_hash',sa.String(64)),
            ('processed_hash',sa.String(64)),('processing_error',sa.String(200)),
            ('next_process_at',sa.DateTime(timezone=True)),('published_at',sa.DateTime(timezone=True)),
            ('list_sequence',sa.Integer())]:
        op.add_column('source_posts',sa.Column(name,kind))
    op.add_column('source_posts',sa.Column('notice_eligible',sa.Boolean(),nullable=False,server_default=sa.true()))
    with op.batch_alter_table('drops') as batch:
        batch.add_column(sa.Column('canonical_id',sa.String(64)))
        batch.create_foreign_key('fk_drop_canonical','drops',['canonical_id'],['id'])
        batch.create_index('ix_drops_canonical_id',['canonical_id'])
    dates=lambda:[sa.Column(k,sa.DateTime(timezone=True),nullable=False) for k in ('created_at','updated_at')]
    op.create_table('source_revisions',
        sa.Column('post_id',sa.String(36),sa.ForeignKey('source_posts.id'),primary_key=True),
        sa.Column('content_hash',sa.String(64),primary_key=True),
        sa.Column('raw_text',sa.Text(),nullable=False),sa.Column('expanded_text',sa.Text(),nullable=False),*dates())
    op.create_table('feed_mentions',
        sa.Column('post_id',sa.String(36),sa.ForeignKey('source_posts.id'),primary_key=True),
        sa.Column('entry_key',sa.String(64),primary_key=True),
        sa.Column('drop_id',sa.String(64),sa.ForeignKey('drops.id'),nullable=False),
        sa.Column('details',sa.JSON(),nullable=False),*dates())
    op.create_index('ix_feed_mentions_drop_id','feed_mentions',['drop_id'])
    op.create_table('feed_seen',
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),primary_key=True),
        sa.Column('post_id',sa.String(36),sa.ForeignKey('source_posts.id'),primary_key=True),
        sa.Column('content_hash',sa.String(64),nullable=False),*dates())
    op.create_table('source_alerts',sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('detail',sa.Text(),nullable=False),sa.Column('status',sa.String(24),nullable=False),
        sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('next_attempt_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('lease_until',sa.DateTime(timezone=True)),*dates())
    with op.batch_alter_table('daily_list_notices') as batch:
        batch.drop_constraint('uq_daily_notice_owner_device',type_='unique')
        batch.create_unique_constraint('uq_daily_notice_post_owner_device',['source_post_id','device_id','user_id'])
    bind=op.get_bind();meta=sa.MetaData()
    connection=sa.Table('source_connections',meta,autoload_with=bind)
    if not bind.execute(sa.select(connection.c.id).where(connection.c.source_name=='cassio_sch')).first():
        moment=datetime.now(timezone.utc)
        bind.execute(connection.insert().values(id=str(uuid.uuid4()),source_name='cassio_sch',source_type='twscrape',
            status='monitoring_paused',is_monitoring=False,consecutive_failures=0,created_at=moment,updated_at=moment))
    tables={n:sa.Table(n,meta,autoload_with=bind) for n in
        ('source_posts','drops','source_revisions','feed_mentions','feed_seen','users')}
    posts={r['id']:dict(r) for r in bind.execute(sa.select(tables['source_posts'])).mappings()}
    canonical={};day_sequences={};now=datetime.now(timezone.utc)
    published=set()
    rows=bind.execute(sa.select(tables['drops']).order_by(tables['drops'].c.created_at,tables['drops'].c.id)).mappings()
    for r in rows:
        post=posts.get(r['source_post_id'])
        if not post or not (post['is_manual_import'] or post['author_username'].lower() in ('lakzonevn','cassio_sch')):continue
        url=urlsplit(r['mint_page_url'])
        # Names are candidate hints only. Legacy merging requires exact collection identity.
        link=url.path.rstrip('/').removesuffix('/drops').removesuffix('/overview')
        identity=(r['chain_id'],(r['contract_address'] or '').lower() or
            (link if url.hostname=='opensea.io' and link.startswith('/collection/') and not url.query else r['id']))
        cid=canonical.setdefault(identity,r['id'])
        if cid!=r['id']:bind.execute(tables['drops'].update().where(tables['drops'].c.id==r['id']).values(canonical_id=cid))
        bind.execute(tables['feed_mentions'].insert().values(post_id=post['id'],entry_key=r['source_entry_key'] or r['id'],
            drop_id=cid,details={'price':r['source_price_text'],'time_wat':r['source_time_text'],'stages':[]},created_at=r['created_at'],updated_at=r['updated_at']))
        published.add(post['id'])
    for post in sorted(posts.values(),key=lambda p:(p['created_at'],p['id'])):
        raw=post['full_text'];digest=hashlib.sha256((raw+'\n'+raw).encode()).hexdigest()
        values=dict(expanded_text=raw,content_hash=digest,processed_hash=digest,notice_eligible=False)
        if post['id'] in published:
            values.update(published_at=post['created_at'])
            if post['is_daily_list']:
                day=post['list_date'];day_sequences[day]=day_sequences.get(day,0)+1
                values.update(list_sequence=day_sequences[day])
        bind.execute(tables['source_posts'].update().where(tables['source_posts'].c.id==post['id']).values(**values))
        bind.execute(tables['source_revisions'].insert().values(post_id=post['id'],content_hash=digest,
            raw_text=raw,expanded_text=raw,created_at=now,updated_at=now))
        # Existing lists are the migration baseline, rather than new unread additions.
        if post['id'] in published:
            for uid in bind.execute(sa.select(tables['users'].c.id)).scalars():
                bind.execute(tables['feed_seen'].insert().values(user_id=uid,post_id=post['id'],content_hash=digest,created_at=now,updated_at=now))


def downgrade():
    raise RuntimeError('This migration retains per-list delivery history. Use a reviewed forward repair; automatic downgrade would lose that history.')
    # Retained for schema documentation only; an automatic destructive downgrade is blocked.
    with op.batch_alter_table('daily_list_notices') as batch:
        batch.drop_constraint('uq_daily_notice_post_owner_device',type_='unique')
        # Multiple notices per day cannot be collapsed without discarding delivery history.
    for name in ('source_alerts','feed_seen','feed_mentions','source_revisions'):op.drop_table(name)
    with op.batch_alter_table('drops') as batch:
        batch.drop_index('ix_drops_canonical_id');batch.drop_constraint('fk_drop_canonical',type_='foreignkey');batch.drop_column('canonical_id')
    for name in ('expanded_text','content_hash','processed_hash','processing_error','next_process_at','published_at','list_sequence','notice_eligible'):
        op.drop_column('source_posts',name)
    op.drop_column('source_connections','next_attempt_at')
    op.drop_column('source_connections','catchup_cursor')
    op.drop_column('source_connections','catchup_until')
