"""Metrics endpoint router with caching."""
from fastapi import APIRouter, Depends, Query
from datetime import datetime
from decimal import Decimal
from typing import Optional

import asyncpg
import redis.asyncio as redis

from src.db.session import get_db_pool
from src.api.schemas import PerformanceMetrics
from src.api.aggregators import MetricsAggregator


router = APIRouter(prefix="/metrics", tags=["Metrics"])


async def get_redis_client() -> redis.Redis:
    """Get Redis client dependency."""
    return redis.from_url(
        "redis://localhost:6379/0",
        encoding="utf-8",
        decode_responses=True
    )


@router.get("", response_model=PerformanceMetrics)
async def get_metrics(
    days: int = Query(30, ge=1, le=365, description="Number of days for calculation"),
    db_pool: asyncpg.Pool = Depends(get_db_pool),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Get performance metrics (Sharpe, WinRate, MaxDD, ProfitFactor).
    
    Metrics are cached for 5 minutes to improve performance.
    Cache is invalidated when a trade is closed.
    
    Returns:
    - Sharpe Ratio (annualized)
    - Win Rate (%)
    - Maximum Drawdown (%)
    - Profit Factor
    - Total Trades
    - Total PnL
    - Average Win/Loss
    """
    aggregator = MetricsAggregator(redis_client)
    metrics_data = await aggregator.get_all_metrics(days)
    
    # Calculate average win and loss
    conn = await db_pool.acquire()
    try:
        avg_query = """
            SELECT 
                AVG(pnl) FILTER (WHERE pnl > 0) as avg_win,
                AVG(ABS(pnl)) FILTER (WHERE pnl < 0) as avg_loss
            FROM positions
            WHERE status IN ('CLOSED', 'STOPPED', 'LIQUIDATED')
              AND closed_at >= NOW() - INTERVAL '%s days'
        """
        row = await conn.fetchrow(avg_query, days)
        
        avg_win = Decimal(str(row["avg_win"])) if row["avg_win"] else None
        avg_loss = Decimal(str(row["avg_loss"])) if row["avg_loss"] else None
    finally:
        await db_pool.release(conn)
    
    return PerformanceMetrics(
        sharpe_ratio=metrics_data.get("sharpe_ratio"),
        win_rate=metrics_data.get("win_rate"),
        max_drawdown=metrics_data.get("max_drawdown"),
        profit_factor=metrics_data.get("profit_factor"),
        total_trades=metrics_data.get("total_trades", 0),
        total_pnl=metrics_data.get("total_pnl", Decimal("0")),
        avg_win=avg_win,
        avg_loss=avg_loss,
        calculated_at=metrics_data.get("calculated_at", datetime.utcnow()),
    )


@router.post("/invalidate")
async def invalidate_metrics_cache(
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Manually invalidate metrics cache.
    
    Called automatically when a trade is closed,
    but can be triggered manually if needed.
    """
    aggregator = MetricsAggregator(redis_client)
    await aggregator.invalidate_cache()
    return {"status": "cache invalidated"}
