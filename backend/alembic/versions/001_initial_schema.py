"""Initial schema for Mintly

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-29 17:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wallets',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('address', sa.String(length=42), nullable=False),
        sa.Column('signing_capability', sa.String(length=30), nullable=False),
        sa.Column('supported_chains', sa.JSON(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('is_demo', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_wallets_address'), 'wallets', ['address'], unique=False)

    op.create_table(
        'source_connections',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('source_name', sa.String(length=50), nullable=False),
        sa.Column('source_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('is_monitoring', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_name')
    )

    op.create_table(
        'source_posts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('post_id', sa.String(length=64), nullable=False),
        sa.Column('author_username', sa.String(length=50), nullable=False),
        sa.Column('full_text', sa.Text(), nullable=False),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('extracted_urls', sa.JSON(), nullable=False),
        sa.Column('is_daily_list', sa.Boolean(), nullable=False),
        sa.Column('is_correction', sa.Boolean(), nullable=False),
        sa.Column('replaces_post_id', sa.String(length=64), nullable=True),
        sa.Column('is_manual_import', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_source_posts_post_id'), 'source_posts', ['post_id'], unique=True)

    op.create_table(
        'drops',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('source_post_id', sa.String(length=36), nullable=True),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('chain', sa.String(length=50), nullable=False),
        sa.Column('chain_id', sa.Integer(), nullable=False),
        sa.Column('contract_address', sa.String(length=42), nullable=True),
        sa.Column('mint_page_url', sa.Text(), nullable=False),
        sa.Column('site_label', sa.String(length=50), nullable=False),
        sa.Column('icon_name', sa.String(length=30), nullable=False),
        sa.Column('status_label', sa.String(length=50), nullable=False),
        sa.Column('status_kind', sa.String(length=20), nullable=False),
        sa.Column('is_supported_integration', sa.Boolean(), nullable=False),
        sa.Column('manual_notice', sa.Text(), nullable=True),
        sa.Column('is_demo', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['source_post_id'], ['source_posts.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_drops_name'), 'drops', ['name'], unique=False)

    op.create_table(
        'mint_stages',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('drop_id', sa.String(length=64), nullable=False),
        sa.Column('stage_name', sa.String(length=50), nullable=False),
        sa.Column('start_time_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time_utc', sa.DateTime(timezone=True), nullable=True),
        sa.Column('price_wei', sa.BigInteger(), nullable=False),
        sa.Column('price_eth_str', sa.String(length=30), nullable=False),
        sa.Column('limit_per_wallet', sa.Integer(), nullable=False),
        sa.Column('eligibility_status', sa.String(length=30), nullable=False),
        sa.Column('eligibility_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('eligibility_wallet_address', sa.String(length=42), nullable=True),
        sa.Column('eligibility_evidence', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['drop_id'], ['drops.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mint_stages_drop_id'), 'mint_stages', ['drop_id'], unique=False)

    op.create_table(
        'mint_authorizations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('wallet_id', sa.String(length=36), nullable=False),
        sa.Column('drop_id', sa.String(length=64), nullable=False),
        sa.Column('stage_id', sa.String(length=64), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('max_price_per_token_wei', sa.BigInteger(), nullable=False),
        sa.Column('max_fee_wei', sa.BigInteger(), nullable=False),
        sa.Column('total_spend_cap_wei', sa.BigInteger(), nullable=False),
        sa.Column('recipient_address', sa.String(length=42), nullable=False),
        sa.Column('user_consent_text', sa.Text(), nullable=False),
        sa.Column('authorized_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_revoked', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['drop_id'], ['drops.id']),
        sa.ForeignKeyConstraint(['stage_id'], ['mint_stages.id']),
        sa.ForeignKeyConstraint(['wallet_id'], ['wallets.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'mint_tasks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('authorization_id', sa.String(length=36), nullable=False),
        sa.Column('wallet_id', sa.String(length=36), nullable=False),
        sa.Column('drop_id', sa.String(length=64), nullable=False),
        sa.Column('stage_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('is_demo', sa.Boolean(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('scheduled_for_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('worker_id', sa.String(length=64), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('assigned_nonce', sa.Integer(), nullable=True),
        sa.Column('prepared_calldata', sa.Text(), nullable=True),
        sa.Column('signed_tx_raw', sa.Text(), nullable=True),
        sa.Column('transaction_hash', sa.String(length=66), nullable=True),
        sa.Column('broadcast_attempts', sa.Integer(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('block_number', sa.BigInteger(), nullable=True),
        sa.Column('actual_gas_used', sa.BigInteger(), nullable=True),
        sa.Column('actual_effective_gas_price', sa.BigInteger(), nullable=True),
        sa.Column('actual_total_cost_wei', sa.BigInteger(), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('explorer_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['authorization_id'], ['mint_authorizations.id']),
        sa.ForeignKeyConstraint(['drop_id'], ['drops.id']),
        sa.ForeignKeyConstraint(['stage_id'], ['mint_stages.id']),
        sa.ForeignKeyConstraint(['wallet_id'], ['wallets.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mint_tasks_idempotency_key'), 'mint_tasks', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_mint_tasks_status'), 'mint_tasks', ['status'], unique=False)
    op.create_index(op.f('ix_mint_tasks_transaction_hash'), 'mint_tasks', ['transaction_hash'], unique=False)

    op.create_table(
        'activity_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('event_type', sa.String(length=40), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('icon_name', sa.String(length=40), nullable=False),
        sa.Column('is_demo', sa.Boolean(), nullable=False),
        sa.Column('event_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activity_events_event_time'), 'activity_events', ['event_time'], unique=False)
    op.create_index(op.f('ix_activity_events_event_type'), 'activity_events', ['event_type'], unique=False)

    op.create_table(
        'notification_devices',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('device_token', sa.String(length=255), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('preferences', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_devices_device_token'), 'notification_devices', ['device_token'], unique=True)


def downgrade() -> None:
    op.drop_table('notification_devices')
    op.drop_table('activity_events')
    op.drop_table('mint_tasks')
    op.drop_table('mint_authorizations')
    op.drop_table('mint_stages')
    op.drop_table('drops')
    op.drop_table('source_posts')
    op.drop_table('source_connections')
    op.drop_table('wallets')
