"""Trades history endpoint router with pagination and filters."""
from fastapi import APIRouter, Depends, Query, HTTPException
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

import asyncpg

from src.db.session import get_db_pool
from src.api.schemas import TradeRecord, TradeListResponse, AccountSide, PositionStatus


router = APIRouter(prefix="/trades", tags=["Trades"])


@router.get("", response_model=TradeListResponse)
async def get_trades(
    limit: int = Query(20, ge=1, le=100, description="Number of items per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    symbol: Optional[str] = Query(None, description="Filter by symbol (e.g., BTCUSDT)"),
    side: Optional[AccountSide] = Query(None, description="Filter by side (LONG/SHORT)"),
    status: Optional[PositionStatus] = Query(None, description="Filter by status"),
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    db_pool: asyncpg.Pool = Depends(get_db_pool),
):
    """
    Get trade history with pagination and filters.
    
    Supports filtering by:
    - Symbol (e.g., BTCUSDT)
    - Side (LONG/SHORT)
    - Status (OPEN/CLOSED/STOPPED/LIQUIDATED)
    - Account ID
    
    Returns paginated results with total count.
    """
    # Build dynamic query
    conditions = ["1=1"]
    params = []
    param_count = 1
    
    if symbol:
        conditions.append(f"symbol = ${param_count}")
        params.append(symbol)
        param_count += 1
    
    if side:
        conditions.append(f"side = ${param_count}")
        params.append(side.value)
        param_count += 1
    
    if status:
        conditions.append(f"status = ${param_count}")
        params.append(status.value)
        param_count += 1
    
    if account_id:
        conditions.append(f"account_id = ${param_count}")
        params.append(account_id)
        param_count += 1
    
    where_clause = " AND ".join(conditions)
    
    conn = await db_pool.acquire()
    try:
        # Get total count
        count_query = f"""
            SELECT COUNT(*) 
            FROM positions 
            WHERE {where_clause}
        """
        total = await conn.fetchval(count_query, *params)
        
        # Get paginated records
        data_query = f"""
            SELECT 
                id,
                signal_id,
                account_id,
                side,
                symbol,
                entry_price,
                exit_price,
                amount,
                leverage,
                pnl,
                status,
                opened_at,
                closed_at,
                trailing_log
            FROM positions
            WHERE {where_clause}
            ORDER BY opened_at DESC
            LIMIT ${param_count} OFFSET ${param_count + 1}
        """
        rows = await conn.fetch(data_query, *params, limit, offset)
        
        trades = []
        for row in rows:
            trades.append(TradeRecord(
                id=row["id"],
                signal_id=row["signal_id"],
                account_id=row["account_id"],
                side=row["side"],
                symbol=row["symbol"],
                entry_price=Decimal(str(row["entry_price"])),
                exit_price=Decimal(str(row["exit_price"])) if row["exit_price"] else None,
                amount=Decimal(str(row["amount"])),
                leverage=row["leverage"],
                pnl=Decimal(str(row["pnl"])) if row["pnl"] else None,
                status=row["status"],
                opened_at=row["opened_at"],
                closed_at=row["closed_at"],
                trailing_log=row["trailing_log"],
            ))
        
        return TradeListResponse(
            items=trades,
            total=total,
            limit=limit,
            offset=offset,
        )
    finally:
        await db_pool.release(conn)


@router.get("/{trade_id}", response_model=TradeRecord)
async def get_trade(
    trade_id: int,
    db_pool: asyncpg.Pool = Depends(get_db_pool),
):
    """Get detailed information about a specific trade."""
    conn = await db_pool.acquire()
    try:
        row = await conn.fetchrow("""
            SELECT 
                id,
                signal_id,
                account_id,
                side,
                symbol,
                entry_price,
                exit_price,
                amount,
                leverage,
                pnl,
                status,
                opened_at,
                closed_at,
                trailing_log
            FROM positions
            WHERE id = $1
        """, trade_id)
        
        if not row:
            raise HTTPException(status_code=404, detail="Trade not found")
        
        return TradeRecord(
            id=row["id"],
            signal_id=row["signal_id"],
            account_id=row["account_id"],
            side=row["side"],
            symbol=row["symbol"],
            entry_price=Decimal(str(row["entry_price"])),
            exit_price=Decimal(str(row["exit_price"])) if row["exit_price"] else None,
            amount=Decimal(str(row["amount"])),
            leverage=row["leverage"],
            pnl=Decimal(str(row["pnl"])) if row["pnl"] else None,
            status=row["status"],
            opened_at=row["opened_at"],
            closed_at=row["closed_at"],
            trailing_log=row["trailing_log"],
        )
    finally:
        await db_pool.release(conn)
