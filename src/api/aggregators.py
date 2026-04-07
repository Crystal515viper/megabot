"""Async aggregators for performance metrics with Redis caching."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any
import json

import asyncpg
import redis.asyncio as redis

from src.db.session import get_db_pool


class MetricsAggregator:
    """Calculates and caches trading performance metrics."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.cache_ttl = 300  # 5 minutes

    async def _get_db_connection(self) -> asyncpg.Connection:
        pool = await get_db_pool()
        return await pool.acquire()

    async def _release_connection(self, conn: asyncpg.Connection):
        pool = await get_db_pool()
        await pool.release(conn)

    async def calculate_sharpe_ratio(
        self, days: int = 30
    ) -> Optional[float]:
        """
        Calculate annualized Sharpe Ratio.
        Formula: (Mean Daily Return / Std Dev of Daily Returns) * sqrt(252)
        """
        cache_key = f"metrics:sharpe:{days}"
        cached = await self.redis.get(cache_key)
        if cached:
            return float(cached)

        conn = await self._get_db_connection()
        try:
            query = """
                SELECT 
                    DATE(created_at) as trade_date,
                    SUM(pnl) as daily_pnl
                FROM daily_metrics
                WHERE created_at >= NOW() - INTERVAL '%s days'
                GROUP BY DATE(created_at)
                ORDER BY trade_date
            """
            rows = await conn.fetch(query, days)
            
            if len(rows) < 2:
                return None

            returns = [float(row["daily_pnl"]) for row in rows if row["daily_pnl"]]
            if not returns:
                return None

            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            std_dev = variance ** 0.5

            if std_dev == 0:
                sharpe = 0.0
            else:
                sharpe = (mean_return / std_dev) * (252 ** 0.5)

            await self.redis.setex(cache_key, self.cache_ttl, str(sharpe))
            return sharpe
        finally:
            await self._release_connection(conn)

    async def calculate_win_rate(self, days: int = 30) -> Optional[float]:
        """
        Calculate Win Rate (%).
        Formula: (Winning Trades / Total Closed Trades) * 100
        """
        cache_key = f"metrics:winrate:{days}"
        cached = await self.redis.get(cache_key)
        if cached:
            return float(cached)

        conn = await self._get_db_connection()
        try:
            query = """
                SELECT 
                    COUNT(*) FILTER (WHERE pnl > 0) as wins,
                    COUNT(*) as total
                FROM positions
                WHERE status IN ('CLOSED', 'STOPPED', 'LIQUIDATED')
                  AND closed_at >= NOW() - INTERVAL '%s days'
            """
            row = await conn.fetchrow(query, days)
            
            if row["total"] == 0:
                return None

            win_rate = (row["wins"] / row["total"]) * 100
            await self.redis.setex(cache_key, self.cache_ttl, str(win_rate))
            return win_rate
        finally:
            await self._release_connection(conn)

    async def calculate_max_drawdown(self, days: int = 30) -> Optional[float]:
        """
        Calculate Maximum Drawdown (%).
        Tracks peak-to-trough decline in cumulative PnL.
        """
        cache_key = f"metrics:maxdd:{days}"
        cached = await self.redis.get(cache_key)
        if cached:
            return float(cached)

        conn = await self._get_db_connection()
        try:
            query = """
                SELECT 
                    created_at,
                    cumulative_pnl
                FROM daily_metrics
                WHERE created_at >= NOW() - INTERVAL '%s days'
                ORDER BY created_at
            """
            rows = await conn.fetch(query, days)
            
            if len(rows) < 2:
                return None

            peak = float(rows[0]["cumulative_pnl"])
            max_dd = 0.0

            for row in rows:
                current = float(row["cumulative_pnl"])
                if current > peak:
                    peak = current
                drawdown = (peak - current) / peak if peak != 0 else 0
                max_dd = max(max_dd, drawdown)

            max_dd_pct = max_dd * 100
            await self.redis.setex(cache_key, self.cache_ttl, str(max_dd_pct))
            return max_dd_pct
        finally:
            await self._release_connection(conn)

    async def calculate_profit_factor(self, days: int = 30) -> Optional[float]:
        """
        Calculate Profit Factor.
        Formula: Gross Profit / Gross Loss
        """
        cache_key = f"metrics:pf:{days}"
        cached = await self.redis.get(cache_key)
        if cached:
            return float(cached)

        conn = await self._get_db_connection()
        try:
            query = """
                SELECT 
                    COALESCE(SUM(pnl) FILTER (WHERE pnl > 0), 0) as gross_profit,
                    COALESCE(SUM(ABS(pnl)) FILTER (WHERE pnl < 0), 0) as gross_loss
                FROM positions
                WHERE status IN ('CLOSED', 'STOPPED', 'LIQUIDATED')
                  AND closed_at >= NOW() - INTERVAL '%s days'
            """
            row = await conn.fetchrow(query, days)
            
            gross_profit = float(row["gross_profit"])
            gross_loss = float(row["gross_loss"])

            if gross_loss == 0:
                pf = float("inf") if gross_profit > 0 else 0.0
            else:
                pf = gross_profit / gross_loss

            await self.redis.setex(cache_key, self.cache_ttl, str(pf))
            return pf
        finally:
            await self._release_connection(conn)

    async def get_total_trades(self, days: int = 30) -> int:
        """Get total number of closed trades."""
        conn = await self._get_db_connection()
        try:
            query = """
                SELECT COUNT(*) 
                FROM positions
                WHERE status IN ('CLOSED', 'STOPPED', 'LIQUIDATED')
                  AND closed_at >= NOW() - INTERVAL '%s days'
            """
            result = await conn.fetchval(query, days)
            return result or 0
        finally:
            await self._release_connection(conn)

    async def get_total_pnl(self, days: int = 30) -> Decimal:
        """Get total realized PnL."""
        conn = await self._get_db_connection()
        try:
            query = """
                SELECT COALESCE(SUM(pnl), 0)
                FROM positions
                WHERE status IN ('CLOSED', 'STOPPED', 'LIQUIDATED')
                  AND closed_at >= NOW() - INTERVAL '%s days'
            """
            result = await conn.fetchval(query, days)
            return Decimal(str(result)) if result else Decimal("0")
        finally:
            await self._release_connection(conn)

    async def get_all_metrics(self, days: int = 30) -> Dict[str, Any]:
        """Aggregate all performance metrics."""
        tasks = {
            "sharpe_ratio": self.calculate_sharpe_ratio(days),
            "win_rate": self.calculate_win_rate(days),
            "max_drawdown": self.calculate_max_drawdown(days),
            "profit_factor": self.calculate_profit_factor(days),
            "total_trades": self.get_total_trades(days),
            "total_pnl": self.get_total_pnl(days),
        }
        
        results = await asyncio.gather(*tasks.values())
        metrics = dict(zip(tasks.keys(), results))
        metrics["calculated_at"] = datetime.utcnow()
        
        return metrics

    async def invalidate_cache(self, pattern: str = "metrics:*"):
        """Invalidate cached metrics by pattern."""
        keys = await self.redis.keys(pattern)
        if keys:
            await self.redis.delete(*keys)
