"""initial migration

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial database schema for trading system."""
    
    # Create enums
    sa.Enum('OPEN', 'CLOSED', 'STOPPED', 'LIQUIDATED', name='positionstatus').create(op.get_bind())
    sa.Enum('LONG', 'SHORT', name='accountside').create(op.get_bind())
    
    # Create signals table
    op.create_table(
        'signals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.String(length=50), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('side', sa.String(length=10), nullable=False),
        sa.Column('entry_price', sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column('stop_loss', sa.Numeric(precision=19, scale=8), nullable=True),
        sa.Column('take_profit', sa.Numeric(precision=19, scale=8), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column('leverage', sa.Integer(), default=1),
        sa.Column('status', sa.String(length=20), default='PENDING'),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), default=dict),
        sa.Column('created_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_signals_account_id_status', 'signals', ['account_id', 'status'])
    op.create_index('ix_signals_created_at_desc', 'signals', ['created_at'], unique=False, postgresql_ops={'created_at': 'DESC'})
    
    # Create positions table
    op.create_table(
        'positions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('signal_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.String(length=50), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('side', sa.String(length=10), nullable=False),
        sa.Column('entry_price', sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column('current_price', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('stop_loss', sa.Numeric(precision=19, scale=8), nullable=True),
        sa.Column('take_profit', sa.Numeric(precision=19, scale=8), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column('leverage', sa.Integer(), default=1),
        sa.Column('status', sa.String(length=20), default='OPEN'),
        sa.Column('realized_pnl', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('unrealized_pnl', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('total_fees', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('trailing_log', postgresql.JSONB(astext_type=sa.Text()), default=list),
        sa.Column('exchange_order_id', sa.String(length=100), nullable=True),
        sa.Column('opened_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=True),
        sa.Column('closed_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['signal_id'], ['signals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('quantity > 0', name='chk_quantity_positive')
    )
    op.create_index('ix_positions_account_id_status', 'positions', ['account_id', 'status'])
    op.create_index('ix_positions_signal_id', 'positions', ['signal_id'])
    op.create_index('ix_positions_created_at_desc', 'positions', ['created_at'], unique=False, postgresql_ops={'created_at': 'DESC'})
    
    # Create account_snapshots table
    op.create_table(
        'account_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.String(length=50), nullable=False),
        sa.Column('balance', sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column('equity', sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column('free_margin', sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column('used_margin', sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column('unrealized_pnl', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('timestamp', postgresql.TIMESTAMPTZ(timezone=True), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'timestamp', name='uq_account_timestamp')
    )
    op.create_index('ix_snapshots_account_id_created_at', 'account_snapshots', ['account_id', 'created_at'])
    
    # Create daily_metrics table
    op.create_table(
        'daily_metrics',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.String(length=50), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('total_trades', sa.Integer(), default=0),
        sa.Column('winning_trades', sa.Integer(), default=0),
        sa.Column('losing_trades', sa.Integer(), default=0),
        sa.Column('gross_profit', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('gross_loss', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('net_pnl', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('total_fees', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('max_drawdown', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('peak_equity', sa.Numeric(precision=19, scale=8), default=0),
        sa.Column('end_equity', sa.Numeric(precision=19, scale=8), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'date', name='uq_account_date')
    )
    op.create_index('ix_daily_metrics_account_id_date', 'daily_metrics', ['account_id', 'date'])
    
    # Create system_logs table
    op.create_table(
        'system_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('service', sa.String(length=50), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('correlation_id', sa.String(length=100), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), default=dict),
        sa.Column('created_at', postgresql.TIMESTAMPTZ(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_logs_level_created_at', 'system_logs', ['level', 'created_at'])
    op.create_index('ix_logs_service_created_at', 'system_logs', ['service', 'created_at'])
    op.create_index('ix_logs_created_at', 'system_logs', ['created_at'])


def downgrade() -> None:
    """Drop all tables and enums."""
    op.drop_index('ix_logs_created_at', table_name='system_logs')
    op.drop_index('ix_logs_service_created_at', table_name='system_logs')
    op.drop_index('ix_logs_level_created_at', table_name='system_logs')
    op.drop_table('system_logs')
    
    op.drop_index('ix_daily_metrics_account_id_date', table_name='daily_metrics')
    op.drop_table('daily_metrics')
    
    op.drop_index('ix_snapshots_account_id_created_at', table_name='account_snapshots')
    op.drop_table('account_snapshots')
    
    op.drop_index('ix_positions_created_at_desc', table_name='positions')
    op.drop_index('ix_positions_signal_id', table_name='positions')
    op.drop_index('ix_positions_account_id_status', table_name='positions')
    op.drop_table('positions')
    
    op.drop_index('ix_signals_created_at_desc', table_name='signals')
    op.drop_index('ix_signals_account_id_status', table_name='signals')
    op.drop_table('signals')
    
    # Drop enums
    sa.Enum(name='positionstatus').drop(op.get_bind())
    sa.Enum(name='accountside').drop(op.get_bind())
