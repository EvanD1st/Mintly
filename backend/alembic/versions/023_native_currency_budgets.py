"""Separate native-currency daily limits; widen cumulative budgets exactly."""
from alembic import op
import sqlalchemy as sa

revision = '023_native_currency_budgets'
down_revision = '022_opensea_owner_fairness'
branch_labels = None
depends_on = None


def upgrade():
    sqlite = op.get_bind().dialect.name == 'sqlite'
    budget_type = sa.String(30) if sqlite else sa.Numeric(30, 0)
    for table in ('automatic_grants', 'copy_rules'):
        with op.batch_alter_table(table) as batch:
            for column in ('budget_wei', 'reserved_wei', 'spent_wei'):
                batch.alter_column(column, existing_type=sa.BigInteger(), type_=budget_type)
        if sqlite:
            for column in ('budget_wei', 'reserved_wei', 'spent_wei'):
                op.execute(sa.text(f"UPDATE {table} SET {column}=printf('%030d',CAST({column} AS INTEGER))"))
    op.add_column('daily_debits', sa.Column('currency', sa.String(8), nullable=False, server_default='ETH'))
    op.create_table('native_daily_limits',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('currency', sa.String(8), primary_key=True),
        sa.Column('daily_limit_wei', budget_type, nullable=True),
        sa.Column('daily_limit_revision', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('daily_limit_status', sa.String(24), nullable=False, server_default='active'),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))


def downgrade():
    # Do not silently truncate new-currency records or wider approved budgets.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM native_daily_limits")).scalar() or bind.execute(
            sa.text("SELECT COUNT(*) FROM daily_debits WHERE currency!='ETH'")).scalar():
        raise RuntimeError('Native-currency accounting must be retained; downgrade requires an audited recovery.')
    for table in ('automatic_grants', 'copy_rules'):
        for column in ('budget_wei', 'reserved_wei', 'spent_wei'):
            if bind.execute(sa.text(f'SELECT COUNT(*) FROM {table} WHERE CAST({column} AS NUMERIC)>9223372036854775807')).scalar():
                raise RuntimeError('Cumulative budgets exceed the old storage limit.')
    op.drop_table('native_daily_limits')
    with op.batch_alter_table('daily_debits') as batch:
        batch.drop_column('currency')
    for table in ('automatic_grants', 'copy_rules'):
        with op.batch_alter_table(table) as batch:
            for column in ('budget_wei', 'reserved_wei', 'spent_wei'):
                batch.alter_column(column, existing_type=sa.Numeric(30,0), type_=sa.BigInteger())
