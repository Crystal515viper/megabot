"""
Example usage of the database layer in an async context.
Demonstrates CRUD operations with proper session management.
"""
import asyncio
from decimal import Decimal
from datetime import datetime, timezone

from src.db.session import async_session_factory, init_db, close_db
from src.db.models import AccountSide, PositionStatus
from src.db.crud import (
    create_signal,
    create_position,
    update_position,
    get_open_positions,
    log_account_snapshot,
    upsert_daily_metric,
    log_system_event,
)


async def example_usage():
    """Demonstrate typical database operations."""
    
    # Initialize database tables (development only)
    await init_db()
    
    async with async_session_factory() as session:
        try:
            # 1. Create a trading signal
            signal = await create_signal(
                session=session,
                account_id="ACC_001",
                symbol="BTCUSDT",
                side=AccountSide.LONG,
                entry_price=Decimal("45000.00"),
                quantity=Decimal("0.1"),
                stop_loss=Decimal("44000.00"),
                take_profit=Decimal("47000.00"),
                leverage=5,
                metadata={"strategy": "breakout", "timeframe": "1h"}
            )
            print(f"Created signal: {signal}")
            
            # 2. Execute signal -> create position
            position = await create_position(
                session=session,
                signal_id=signal.id,
                account_id="ACC_001",
                symbol="BTCUSDT",
                side=AccountSide.LONG,
                entry_price=Decimal("45000.00"),
                quantity=Decimal("0.1"),
                exchange_order_id="BINANCE_ORDER_123456",
                stop_loss=Decimal("44000.00"),
                take_profit=Decimal("47000.00"),
                leverage=5
            )
            print(f"Created position: {position}")
            
            # 3. Update position with trailing stop
            updated_position = await update_position(
                session=session,
                position_id=position.id,
                current_price=Decimal("45500.00"),
                unrealized_pnl=Decimal("50.00"),
                stop_loss=Decimal("44500.00"),  # Trailing stop adjustment
                trailing_log_entry={
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": "trailing_stop_update",
                    "old_sl": "44000.00",
                    "new_sl": "44500.00",
                    "price": "45500.00"
                }
            )
            print(f"Updated position: {updated_position}")
            
            # 4. Get open positions
            open_positions = await get_open_positions(
                session=session,
                account_id="ACC_001"
            )
            print(f"Open positions count: {len(open_positions)}")
            
            # 5. Log account snapshot
            snapshot = await log_account_snapshot(
                session=session,
                account_id="ACC_001",
                balance=Decimal("10000.00"),
                equity=Decimal("10050.00"),
                free_margin=Decimal("8000.00"),
                used_margin=Decimal("2000.00"),
                unrealized_pnl=Decimal("50.00")
            )
            print(f"Logged snapshot: {snapshot}")
            
            # 6. Upsert daily metric
            today = datetime.now(timezone.utc).date()
            metric = await upsert_daily_metric(
                session=session,
                account_id="ACC_001",
                date=datetime(today.year, today.month, today.day),
                total_trades=1,
                winning_trades=0,
                losing_trades=0,
                net_pnl=Decimal("50.00"),
                end_equity=Decimal("10050.00")
            )
            print(f"Daily metric: {metric}")
            
            # 7. Log system event
            log_entry = await log_system_event(
                session=session,
                service="bot_long",
                level="INFO",
                message="Position opened successfully",
                correlation_id="corr_123456",
                payload={
                    "position_id": position.id,
                    "symbol": "BTCUSDT",
                    "entry_price": str(position.entry_price)
                }
            )
            print(f"System log: {log_entry}")
            
        except Exception as e:
            await session.rollback()
            print(f"Error: {e}")
            raise
        finally:
            await close_db()


if __name__ == "__main__":
    asyncio.run(example_usage())
