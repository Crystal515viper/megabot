"""Pydantic V2 schemas for API responses and requests."""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    STOPPED = "STOPPED"
    LIQUIDATED = "LIQUIDATED"


class AccountSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


# --- Status Schemas ---
class SystemHealth(BaseModel):
    status: str = Field(..., description="Overall system status")
    orchestrator: bool = Field(..., description="Orchestrator health")
    bot_long: bool = Field(..., description="Long bot health")
    bot_short: bool = Field(..., description="Short bot health")
    database: bool = Field(..., description="Database connection status")
    redis: bool = Field(..., description="Redis connection status")
    last_heartbeat: Optional[datetime] = Field(None, description="Last bot heartbeat")


class BalanceInfo(BaseModel):
    total_equity: Decimal = Field(..., description="Total equity in USDT")
    free_balance: Decimal = Field(..., description="Free balance available")
    locked_balance: Decimal = Field(..., description="Balance locked in positions")
    unrealized_pnl: Decimal = Field(..., description="Unrealized PnL from open positions")


class PositionSummary(BaseModel):
    id: int
    account_id: int
    side: AccountSide
    symbol: str
    entry_price: Decimal
    current_price: Decimal
    amount: Decimal
    leverage: int
    unrealized_pnl: Decimal
    status: PositionStatus
    opened_at: datetime


class StatusResponse(BaseModel):
    health: SystemHealth
    balance: BalanceInfo
    open_positions: List[PositionSummary]
    timestamp: datetime


# --- Trades Schemas ---
class TradeRecord(BaseModel):
    id: int
    signal_id: Optional[int]
    account_id: int
    side: AccountSide
    symbol: str
    entry_price: Decimal
    exit_price: Optional[Decimal]
    amount: Decimal
    leverage: int
    pnl: Optional[Decimal]
    status: PositionStatus
    opened_at: datetime
    closed_at: Optional[datetime]
    trailing_log: Optional[Dict[str, Any]]


class TradeListResponse(BaseModel):
    items: List[TradeRecord]
    total: int
    limit: int
    offset: int


# --- Metrics Schemas ---
class PerformanceMetrics(BaseModel):
    sharpe_ratio: Optional[float] = Field(None, description="Sharpe Ratio (annualized)")
    win_rate: Optional[float] = Field(None, description="Win Rate (%)")
    max_drawdown: Optional[float] = Field(None, description="Maximum Drawdown (%)")
    profit_factor: Optional[float] = Field(None, description="Profit Factor")
    total_trades: int = Field(..., description="Total closed trades")
    total_pnl: Decimal = Field(..., description="Total realized PnL")
    avg_win: Optional[Decimal] = Field(None, description="Average winning trade")
    avg_loss: Optional[Decimal] = Field(None, description="Average losing trade")
    calculated_at: datetime


# --- Stream Schemas ---
class StreamPositionUpdate(BaseModel):
    position_id: int
    symbol: str
    side: AccountSide
    current_price: Decimal
    unrealized_pnl: Decimal
    trailing_stop_price: Optional[Decimal]
    status: PositionStatus
    timestamp: datetime
