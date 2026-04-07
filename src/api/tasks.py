"""Background tasks for API service."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
import logging

import asyncpg
import redis.asyncio as redis

from src.db.session import get_db_pool
from src.api.aggregators import MetricsAggregator

logger = logging.getLogger(__name__)


async def calculate_daily_metrics():
    """
    Background task: Calculate and store daily metrics.
    
    Runs once per day (at midnight UTC) to aggregate:
    - Total trades closed
    - Total PnL
    - Win rate
    - Average win/loss
    - Sharpe ratio
    - Max drawdown
    
    Results are stored in daily_metrics table for historical analysis.
    """
    logger.info("Starting daily metrics calculation...")
    
    db_pool = await get_db_pool()
    redis_client = redis.from_url("redis://localhost:6379/0")
    
    try:
        conn = await db_pool.acquire()
        
        # Calculate metrics for yesterday
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        
        query = """
            SELECT 
                COUNT(*) FILTER (WHERE pnl > 0) as wins,
                COUNT(*) FILTER (WHERE pnl < 0) as losses,
                COUNT(*) as total_trades,
                COALESCE(SUM(pnl), 0) as total_pnl,
                COALESCE(AVG(pnl) FILTER (WHERE pnl > 0), 0) as avg_win,
                COALESCE(AVG(ABS(pnl)) FILTER (WHERE pnl < 0), 0) as avg_loss,
                COALESCE(MAX(pnl), 0) as max_win,
                COALESCE(MIN(pnl), 0) as max_loss
            FROM positions
            WHERE status IN ('CLOSED', 'STOPPED', 'LIQUIDATED')
              AND DATE(closed_at) = $1
        """
        
        row = await conn.fetchrow(query, yesterday)
        
        if row["total_trades"] > 0:
            win_rate = (row["wins"] / row["total_trades"]) * 100
            profit_factor = (
                row["avg_win"] * row["wins"] / (row["avg_loss"] * row["losses"])
                if row["losses"] > 0 and row["avg_loss"] > 0
                else float("inf") if row["wins"] > 0 else 0
            )
        else:
            win_rate = 0
            profit_factor = 0
        
        # Get cumulative PnL up to yesterday
        cumulative_query = """
            SELECT COALESCE(SUM(pnl), 0) as cumulative_pnl
            FROM positions
            WHERE status IN ('CLOSED', 'STOPPED', 'LIQUIDATED')
              AND DATE(closed_at) <= $1
        """
        cumulative_row = await conn.fetchrow(cumulative_query, yesterday)
        
        # Insert daily metrics
        insert_query = """
            INSERT INTO daily_metrics (
                date,
                total_trades,
                total_pnl,
                cumulative_pnl,
                wins,
                losses,
                win_rate,
                avg_win,
                avg_loss,
                max_win,
                max_loss,
                profit_factor,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
            ON CONFLICT (date) DO UPDATE SET
                total_trades = EXCLUDED.total_trades,
                total_pnl = EXCLUDED.total_pnl,
                cumulative_pnl = EXCLUDED.cumulative_pnl,
                wins = EXCLUDED.wins,
                losses = EXCLUDED.losses,
                win_rate = EXCLUDED.win_rate,
                avg_win = EXCLUDED.avg_win,
                avg_loss = EXCLUDED.avg_loss,
                max_win = EXCLUDED.max_win,
                max_loss = EXCLUDED.max_loss,
                profit_factor = EXCLUDED.profit_factor
        """
        
        await conn.execute(
            insert_query,
            yesterday,
            row["total_trades"],
            Decimal(str(row["total_pnl"])),
            Decimal(str(cumulative_row["cumulative_pnl"])),
            row["wins"],
            row["losses"],
            win_rate,
            Decimal(str(row["avg_win"])),
            Decimal(str(row["avg_loss"])),
            Decimal(str(row["max_win"])),
            Decimal(str(row["max_loss"])),
            profit_factor,
        )
        
        logger.info(
            f"Daily metrics calculated for {yesterday}: "
            f"{row['total_trades']} trades, PnL: {row['total_pnl']}"
        )
        
        # Invalidate metrics cache
        aggregator = MetricsAggregator(redis_client)
        await aggregator.invalidate_cache()
        
    except Exception as e:
        logger.error(f"Error calculating daily metrics: {e}")
    finally:
        if "conn" in locals():
            await db_pool.release(conn)
        await redis_client.close()


async def schedule_daily_metrics():
    """
    Schedule daily metrics calculation to run at midnight UTC.
    """
    while True:
        now = datetime.utcnow()
        tomorrow = now.date() + timedelta(days=1)
        midnight = datetime.combine(tomorrow, datetime.min.time())
        
        sleep_seconds = (midnight - now).total_seconds()
        
        logger.info(f"Scheduling daily metrics in {sleep_seconds:.0f} seconds")
        
        await asyncio.sleep(sleep_seconds)
        
        # Run the calculation
        await calculate_daily_metrics()
        
        # Small delay to avoid running exactly at midnight edge cases
        await asyncio.sleep(1)


async def cleanup_old_data(days_to_keep: int = 90):
    """
    Background task: Clean up old data from system_logs.
    
    Keeps only the last N days of logs to prevent database bloat.
    Runs weekly.
    """
    logger.info(f"Cleaning up system_logs older than {days_to_keep} days...")
    
    db_pool = await get_db_pool()
    
    try:
        conn = await db_pool.acquire()
        
        query = """
            DELETE FROM system_logs
            WHERE created_at < NOW() - INTERVAL '%s days'
        """
        
        result = await conn.execute(query, days_to_keep)
        
        # Extract number of deleted rows from result string (e.g., "DELETE 150")
        deleted_count = int(result.split()[-1]) if result else 0
        
        logger.info(f"Deleted {deleted_count} old log entries")
        
    except Exception as e:
        logger.error(f"Error cleaning up old data: {e}")
    finally:
        if "conn" in locals():
            await db_pool.release(conn)


async def schedule_weekly_cleanup():
    """
    Schedule weekly cleanup task.
    """
    while True:
        # Run every Sunday at 2 AM UTC
        now = datetime.utcnow()
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0 and now.hour >= 2:
            days_until_sunday = 7
        
        next_sunday = now + timedelta(days=days_until_sunday)
        next_run = next_sunday.replace(hour=2, minute=0, second=0, microsecond=0)
        
        sleep_seconds = (next_run - now).total_seconds()
        
        logger.info(f"Scheduling weekly cleanup in {sleep_seconds:.0f} seconds")
        
        await asyncio.sleep(sleep_seconds)
        
        await cleanup_old_data()
        
        await asyncio.sleep(1)
