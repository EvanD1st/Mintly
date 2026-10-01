"""One-use non-custodial mint permissions."""
from alembic import op
import sqlalchemy as sa
revision='005_mint_permissions'
down_revision='004_mint_plan_quotes'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('mint_permissions',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('plan_id',sa.String(36),sa.ForeignKey('mint_plans.id'),nullable=False),
        sa.Column('code_hash',sa.String(64),nullable=False),
        sa.Column('typed_data',sa.JSON(),nullable=False),sa.Column('execution',sa.JSON(),nullable=False),
        sa.Column('signature',sa.Text()),sa.Column('status',sa.String(30),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('execute_after',sa.DateTime(timezone=True),nullable=False),
        sa.Column('signature_deadline',sa.DateTime(timezone=True),nullable=False),
        sa.Column('submitted_at',sa.DateTime(timezone=True)),sa.Column('tx_hash',sa.String(66)),
        sa.Column('raw_transaction',sa.Text()),sa.Column('note',sa.Text(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for name in ['user_id','plan_id','status','execute_after']:
        op.create_index('ix_mint_permissions_'+name,'mint_permissions',[name])
    op.create_index('ix_mint_permissions_code_hash','mint_permissions',['code_hash'],unique=True)

def downgrade():
    op.drop_table('mint_permissions')
