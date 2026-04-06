"""
Asynchronous CRUD operations for trading system entities.
All functions use SQLAlchemy 2.0 syntax with AsyncSession.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import (
    Signal, Position, AccountSnapshot, DailyMetric, SystemLog,
    PositionStatus, AccountSide
)


async def create_signal(
    session: AsyncSession,
    account_id: str,
    symbol: str,
    side: AccountSide,
    entry_price: Decimal,
    quantity: Decimal,
    stop_loss: Optional[Decimal] = None,
    take_profit: Optional[Decimal] = None,
    leverage: int = 1,
    metadata: Optional[Dict[str, Any]] = None
) -> Signal:
    """
    Create a new trading signal.
    
    Args:
        session: AsyncSession instance
        account_id: Trading account identifier
        symbol: Trading pair symbol (e.g., BTCUSDT)
        side: LONG or SHORT
        entry_price: Target entry price
        quantity: Position size
        stop_loss: Optional stop-loss price
        take_profit: Optional take-profit price
        leverage: Leverage multiplier (default: 1)
        metadata: Additional signal metadata
        
    Returns:
        Created Signal instance
    """
    signal = Signal(
        account_id=account_id,
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        quantity=quantity,
        stop_loss=stop_loss,
        take_profit=take_profit,
        leverage=leverage,
        status="PENDING",
        metadata=metadata or {}
    )
    session.add(signal)
    await session.flush()
    await session.refresh(signal)
    return signal


async def create_position(
    session: AsyncSession,
    signal_id: int,
    account_id: str,
    symbol: str,
    side: AccountSide,
    entry_price: Decimal,
    quantity: Decimal,
    exchange_order_id: Optional[str] = None,
    stop_loss: Optional[Decimal] = None,
    take_profit: Optional[Decimal] = None,
    leverage: int = 1
) -> Position:
    """
    Create a new trading position from an executed signal.
    
    Args:
        session: AsyncSession instance
        signal_id: Reference to parent signal
        account_id: Trading account identifier
        symbol: Trading pair symbol
        side: LONG or SHORT
        entry_price: Actual filled entry price
        quantity: Filled position size
        exchange_order_id: Exchange order ID for tracking
        stop_loss: Initial stop-loss
        take_profit: Initial take-profit
        leverage: Leverage used
        
    Returns:
        Created Position instance
    """
    position = Position(
        signal_id=signal_id,
        account_id=account_id,
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        current_price=entry_price,
        quantity=quantity,
        leverage=leverage,
        stop_loss=stop_loss,
        take_profit=take_profit,
        status=PositionStatus.OPEN,
        exchange_order_id=exchange_order_id,
        opened_at=datetime.now(timezone.utc),
        trailing_log=[]
    )
    session.add(position)
    await session.flush()
    await session.refresh(position)
    
    # Update signal status
    await session.execute(
        update(Signal)
        .where(Signal.id == signal_id)
        .values(status="EXECUTED")
    )
    
    return position


async def update_position(
    session: AsyncSession,
    position_id: int,
    current_price: Optional[Decimal] = None,
    stop_loss: Optional[Decimal] = None,
    take_profit: Optional[Decimal] = None,
    realized_pnl: Optional[Decimal] = None,
    unrealized_pnl: Optional[Decimal] = None,
    total_fees: Optional[Decimal] = None,
    status: Optional[PositionStatus] = None,
    trailing_log_entry: Optional[Dict[str, Any]] = None
) -> Optional[Position]:
    """
    Update an existing position with new values.
    
    Args:
        session: AsyncSession instance
        position_id: Position ID to update
        current_price: Current market price
        stop_loss: Updated stop-loss (for trailing stops)
        take_profit: Updated take-profit
        realized_pnl: Realized PnL on close
        unrealized_pnl: Current unrealized PnL
        total_fees: Accumulated fees
        status: New position status
        trailing_log_entry: Entry to append to trailing_log JSONB
        
    Returns:
        Updated Position instance or None if not found
    """
    update_data = {}
    if current_price is not None:
        update_data["current_price"] = current_price
    if stop_loss is not None:
        update_data["stop_loss"] = stop_loss
    if take_profit is not None:
        update_data["take_profit"] = take_profit
    if realized_pnl is not None:
        update_data["realized_pnl"] = realized_pnl
    if unrealized_pnl is not None:
        update_data["unrealized_pnl"] = unrealized_pnl
    if total_fees is not None:
        update_data["total_fees"] = total_fees
    if status is not None:
        update_data["status"] = status
        if status in [PositionStatus.CLOSED, PositionStatus.STOPPED, PositionStatus.LIQUIDATED]:
            update_data["closed_at"] = datetime.now(timezone.utc)
    
    if update_data:
        await session.execute(
            update(Position)
            .where(Position.id == position_id)
            .values(**update_data)
        )
    
    if trailing_log_entry is not None:
        position = await session.get(Position, position_id)
        if position:
            log = position.trailing_log or []
            log.append(trailing_log_entry)
            position.trailing_log = log
    
    await session.commit()
    return await session.get(Position, position_id)


async def get_position_by_id(
    session: AsyncSession,
    position_id: int
) -> Optional[Position]:
    """
    Fetch a position by ID with related signal data.
    
    Args:
        session: AsyncSession instance
        position_id: Position ID
        
    Returns:
        Position instance or None
    """
    result = await session.execute(
        select(Position)
        .options(selectinload(Position.signal))
        .where(Position.id == position_id)
    )
    return result.scalar_one_or_none()


async def get_open_positions(
    session: AsyncSession,
    account_id: Optional[str] = None,
    symbol: Optional[str] = None
) -> List[Position]:
    """
    Fetch all open positions, optionally filtered by account or symbol.
    
    Args:
        session: AsyncSession instance
        account_id: Filter by account ID
        symbol: Filter by symbol
        
    Returns:
        List of open Position instances
    """
    query = select(Position).where(Position.status == PositionStatus.OPEN)
    
    if account_id:
        query = query.where(Position.account_id == account_id)
    if symbol:
        query = query.where(Position.symbol == symbol)
    
    result = await session.execute(query.order_by(Position.created_at.desc()))
    return list(result.scalars().all())


async def log_account_snapshot(
    session: AsyncSession,
    account_id: str,
    balance: Decimal,
    equity: Decimal,
    free_margin: Decimal,
    used_margin: Decimal,
    unrealized_pnl: Decimal = Decimal("0"),
    timestamp: Optional[datetime] = None
) -> AccountSnapshot:
    """
    Record an account snapshot for equity curve tracking.
    
    Args:
        session: AsyncSession instance
        account_id: Trading account identifier
        balance: Account balance
        equity: Total equity (balance + unrealized PnL)
        free_margin: Available margin
        used_margin: Margin in use
        unrealized_pnl: Current unrealized PnL
        timestamp: Snapshot timestamp (default: now)
        
    Returns:
        Created AccountSnapshot instance
    """
    snapshot = AccountSnapshot(
        account_id=account_id,
        balance=balance,
        equity=equity,
        free_margin=free_margin,
        used_margin=used_margin,
        unrealized_pnl=unrealized_pnl,
        timestamp=timestamp or datetime.now(timezone.utc)
    )
    session.add(snapshot)
    await session.flush()
    await session.refresh(snapshot)
    return snapshot


async def upsert_daily_metric(
    session: AsyncSession,
    account_id: str,
    date: datetime,
    total_trades: int = 0,
    winning_trades: int = 0,
    losing_trades: int = 0,
    gross_profit: Decimal = Decimal("0"),
    gross_loss: Decimal = Decimal("0"),
    net_pnl: Decimal = Decimal("0"),
    total_fees: Decimal = Decimal("0"),
    max_drawdown: Decimal = Decimal("0"),
    peak_equity: Decimal = Decimal("0"),
    end_equity: Decimal = Decimal("0")
) -> DailyMetric:
    """
    Create or update daily aggregated metrics.
    
    Args:
        session: AsyncSession instance
        account_id: Trading account identifier
        date: Metric date
        total_trades: Total trades count
        winning_trades: Winning trades count
        losing_trades: Losing trades count
        gross_profit: Total gross profit
        gross_loss: Total gross loss
        net_pnl: Net PnL
        total_fees: Total fees paid
        max_drawdown: Maximum drawdown
        peak_equity: Peak equity during day
        end_equity: End-of-day equity
        
    Returns:
        Created/updated DailyMetric instance
    """
    # Check if exists
    result = await session.execute(
        select(DailyMetric).where(
            DailyMetric.account_id == account_id,
            DailyMetric.date == date
        )
    )
    metric = result.scalar_one_or_none()
    
    if metric:
        # Update existing
        metric.total_trades += total_trades
        metric.winning_trades += winning_trades
        metric.losing_trades += losing_trades
        metric.gross_profit += gross_profit
        metric.gross_loss += gross_loss
        metric.net_pnl += net_pnl
        metric.total_fees += total_fees
        metric.max_drawdown = max(metric.max_drawdown, max_drawdown)
        metric.peak_equity = max(metric.peak_equity, peak_equity)
        metric.end_equity = end_equity
    else:
        # Create new
        metric = DailyMetric(
            account_id=account_id,
            date=date,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_pnl=net_pnl,
            total_fees=total_fees,
            max_drawdown=max_drawdown,
            peak_equity=peak_equity,
            end_equity=end_equity
        )
        session.add(metric)
    
    await session.flush()
    await session.refresh(metric)
    return metric


async def log_system_event(
    session: AsyncSession,
    service: str,
    level: str,
    message: str,
    correlation_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None
) -> SystemLog:
    """
    Log a system event for audit trail.
    
    Args:
        session: AsyncSession instance
        service: Service name (orchestrator, bot_long, bot_short, api_gateway)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        message: Log message
        correlation_id: Request correlation ID for tracing
        payload: Additional structured data
        
    Returns:
        Created SystemLog instance
    """
    log_entry = SystemLog(
        service=service,
        level=level,
        message=message,
        correlation_id=correlation_id,
        payload=payload or {}
    )
    session.add(log_entry)
    await session.flush()
    await session.refresh(log_entry)
    return log_entry


async def get_recent_logs(
    session: AsyncSession,
    service: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = 100
) -> List[SystemLog]:
    """
    Fetch recent system logs with optional filters.
    
    Args:
        session: AsyncSession instance
        service: Filter by service name
        level: Filter by log level
        limit: Maximum number of logs to return
        
    Returns:
        List of SystemLog instances
    """
    query = select(SystemLog).order_by(SystemLog.created_at.desc()).limit(limit)
    
    if service:
        query = query.where(SystemLog.service == service)
    if level:
        query = query.where(SystemLog.level == level)
    
    result = await session.execute(query)
    return list(result.scalars().all())
