"""Status endpoint router."""
from fastapi import APIRouter, Depends
from datetime import datetime
from decimal import Decimal

import redis.asyncio as redis
import asyncpg

from src.db.session import get_db_pool
from src.api.schemas import (
    StatusResponse,
    SystemHealth,
    BalanceInfo,
    PositionSummary,
)


router = APIRouter(prefix="/status", tags=["Status"])


async def get_redis_client() -> redis.Redis:
    """Get Redis client dependency."""
    return redis.from_url(
        "redis://localhost:6379/0",
        encoding="utf-8",
        decode_responses=True
    )


@router.get("", response_model=StatusResponse)
async def get_status(
    db_pool: asyncpg.Pool = Depends(get_db_pool),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Get system health, balance, and open positions.
    
    Returns comprehensive status including:
    - Health of all components (orchestrator, bots, DB, Redis)
    - Account balance information
    - List of currently open positions
    """
    # Check component health
    health_checks = {
        "database": False,
        "redis": False,
        "orchestrator": False,
        "bot_long": False,
        "bot_short": False,
    }
    
    # Database check
    try:
        conn = await db_pool.acquire()
        await conn.fetchval("SELECT 1")
        await db_pool.release(conn)
        health_checks["database"] = True
    except Exception:
        pass
    
    # Redis check
    try:
        await redis_client.ping()
        health_checks["redis"] = True
    except Exception:
        pass
    
    # Bot heartbeat check (last 10 seconds)
    try:
        long_heartbeat = await redis_client.get("bot:long:heartbeat")
        short_heartbeat = await redis_client.get("bot:short:heartbeat")
        
        if long_heartbeat:
            health_checks["bot_long"] = True
        if short_heartbeat:
            health_checks["bot_short"] = True
            
        # Orchestrator is healthy if at least one bot is healthy
        health_checks["orchestrator"] = health_checks["bot_long"] or health_checks["bot_short"]
    except Exception:
        pass
    
    # Get balance from Redis (updated by bots)
    balance_data = await redis_client.hgetall("account:balance")
    total_equity = Decimal(balance_data.get("total_equity", "0"))
    free_balance = Decimal(balance_data.get("free_balance", "0"))
    locked_balance = Decimal(balance_data.get("locked_balance", "0"))
    unrealized_pnl = Decimal(balance_data.get("unrealized_pnl", "0"))
    
    # Get open positions from DB
    conn = await db_pool.acquire()
    try:
        rows = await conn.fetch("""
            SELECT 
                p.id,
                p.account_id,
                p.side,
                p.symbol,
                p.entry_price,
                p.amount,
                p.leverage,
                p.status,
                p.opened_at,
                s.price as current_price
            FROM positions p
            LEFT JOIN LATERAL (
                SELECT price FROM signals 
                WHERE symbol = p.symbol 
                ORDER BY timestamp DESC LIMIT 1
            ) s ON true
            WHERE p.status = 'OPEN'
            ORDER BY p.opened_at DESC
        """)
        
        positions = []
        for row in rows:
            entry = Decimal(str(row["entry_price"]))
            current = Decimal(str(row["current_price"])) if row["current_price"] else entry
            amount = Decimal(str(row["amount"]))
            leverage = row["leverage"]
            
            # Calculate unrealized PnL
            if row["side"] == "LONG":
                pnl = (current - entry) * amount * leverage
            else:
                pnl = (entry - current) * amount * leverage
            
            positions.append(PositionSummary(
                id=row["id"],
                account_id=row["account_id"],
                side=row["side"],
                symbol=row["symbol"],
                entry_price=entry,
                current_price=current,
                amount=amount,
                leverage=leverage,
                unrealized_pnl=pnl,
                status=row["status"],
                opened_at=row["opened_at"],
            ))
    finally:
        await db_pool.release(conn)
    
    overall_status = "healthy" if all(health_checks.values()) else "degraded"
    
    return StatusResponse(
        health=SystemHealth(
            status=overall_status,
            orchestrator=health_checks["orchestrator"],
            bot_long=health_checks["bot_long"],
            bot_short=health_checks["bot_short"],
            database=health_checks["database"],
            redis=health_checks["redis"],
            last_heartbeat=datetime.utcnow(),
        ),
        balance=BalanceInfo(
            total_equity=total_equity,
            free_balance=free_balance,
            locked_balance=locked_balance,
            unrealized_pnl=unrealized_pnl,
        ),
        open_positions=positions,
        timestamp=datetime.utcnow(),
    )
