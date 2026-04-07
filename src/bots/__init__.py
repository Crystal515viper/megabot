"""
Bots Module for Trading System.

Contains Long and Short trading bots with:
- Redis queue subscription
- Exchange integration via ccxt.pro
- State machine for position management
- Trailing stop implementation
- Error handling with exponential backoff
"""

from src.bots.base_bot import BaseTradingBot, BotConfig, PositionState, TradingPosition
from src.bots.long_bot import LongTradingBot, create_long_bot_config
from src.bots.short_bot import ShortTradingBot, create_short_bot_config

__all__ = [
    "BaseTradingBot",
    "BotConfig",
    "PositionState",
    "TradingPosition",
    "LongTradingBot",
    "create_long_bot_config",
    "ShortTradingBot",
    "create_short_bot_config",
]
