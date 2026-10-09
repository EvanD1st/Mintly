"""Archive plans/tasks and preserve append-only plan records."""
from datetime import datetime, timezone
from decimal import Decimal
import uuid
from alembic import op
import sqlalchemy as sa

revision = '008_plan_history'
down_revision = '007_automatic_execution'
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table('mint_plans') as batch:
        batch.add_column(sa.Column('archived_at', sa.DateTime(timezone=True)))
        batch.add_column(sa.Column('automatic_drop_id', sa.String(64)))
        batch.add_column(sa.Column('automatic_stage_id', sa.String(64)))
    with op.batch_alter_table('mint_tasks') as batch:
        batch.add_column(sa.Column('plan_id', sa.String(36)))
        batch.add_column(sa.Column('archived_at', sa.DateTime(timezone=True)))
        batch.create_foreign_key('fk_task_plan', 'mint_plans', ['plan_id'], ['id'])
        batch.create_index('ix_mint_tasks_plan_id', ['plan_id'])
    records = op.create_table('mint_plan_records',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('plan_id', sa.String(36), sa.ForeignKey('mint_plans.id'), nullable=False),
        sa.Column('event', sa.String(30), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    for column in ('user_id', 'plan_id', 'recorded_at'):
        op.create_index('ix_mint_plan_records_' + column, 'mint_plan_records', [column])
    conn = op.get_bind()
    meta = sa.MetaData()
    plans = sa.Table('mint_plans', meta, autoload_with=conn)
    wallets = sa.Table('wallets', meta, autoload_with=conn)
    def eth(value):
        return format(Decimal(value) / Decimal(10**18), 'f') if value is not None else None
    now = datetime.now(timezone.utc)
    for row in conn.execute(sa.select(plans, wallets.c.address.label('wallet_address')).join(
            wallets, wallets.c.id == plans.c.wallet_id)).mappings():
        snapshot = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in row.items()}
        snapshot['opensea_url'] = row['opensea_url']
        for source, target in [('price_wei', 'price_eth'), ('mint_value_wei', 'mint_value_eth'),
                               ('estimated_network_fee_wei', 'estimated_network_fee_eth')]:
            snapshot[target] = eth(row[source])
        conn.execute(records.insert().values(id=str(uuid.uuid4()), user_id=row['user_id'], plan_id=row['id'],
            event='retained', recorded_at=row['created_at'], snapshot=snapshot, created_at=now, updated_at=now))


def downgrade():
    op.drop_table('mint_plan_records')
    with op.batch_alter_table('mint_tasks') as batch:
        batch.drop_index('ix_mint_tasks_plan_id')
        batch.drop_constraint('fk_task_plan', type_='foreignkey')
        batch.drop_column('archived_at')
        batch.drop_column('plan_id')
    with op.batch_alter_table('mint_plans') as batch:
        for column in ('automatic_stage_id', 'automatic_drop_id', 'archived_at'):
            batch.drop_column(column)
