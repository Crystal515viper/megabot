"""Database package for trading system."""
from src.db.session import Base, engine, async_session_factory, get_db_session, init_db, close_db
from src.db.models import (
    Signal, Position, AccountSnapshot, DailyMetric, SystemLog,
    PositionStatus, AccountSide
)
from src.db.crud import (
    create_signal, create_position, update_position, get_position_by_id,
    get_open_positions, log_account_snapshot, upsert_daily_metric,
    log_system_event, get_recent_logs
)

__all__ = [
    # Session
    "Base", "engine", "async_session_factory", "get_db_session", "init_db", "close_db",
    # Models
    "Signal", "Position", "AccountSnapshot", "DailyMetric", "SystemLog",
    "PositionStatus", "AccountSide",
    # CRUD
    "create_signal", "create_position", "update_position", "get_position_by_id",
    "get_open_positions", "log_account_snapshot", "upsert_daily_metric",
    "log_system_event", "get_recent_logs",
]
