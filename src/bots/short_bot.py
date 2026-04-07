"""
Short Trading Bot.

Specialized bot for SHORT positions.
Listens to queue:signals_short and executes short trades.
"""

import os
import asyncio
from loguru import logger

from src.bots.base_bot import BaseTradingBot, BotConfig


class ShortTradingBot(BaseTradingBot):
    """
    Short-side trading bot.
    
    Subscribes to queue:signals_short and executes SELL/SHORT orders.
    """
    
    def __init__(self, config: BotConfig):
        # Override queue settings for SHORT
        config.queue_name = "queue:signals_short"
        config.heartbeat_key = "bot:short:heartbeat"
        config.account_side = "SHORT"
        
        super().__init__(config)
        logger.info("[ShortBot] Initialized for SHORT trading")
    
    def get_queue_name(self) -> str:
        """Return SHORT queue name."""
        return "queue:signals_short"


def create_short_bot_config() -> BotConfig:
    """
    Create bot configuration from environment variables.
    
    Expected ENV vars:
    - SHORT_BOT_API_KEY
    - SHORT_BOT_API_SECRET
    - EXCHANGE_ID (default: binance)
    - PAPER_TRADING (default: True)
    - REDIS_URL
    """
    return BotConfig(
        bot_name="bot-short",
        account_side="SHORT",
        exchange_id=os.getenv("EXCHANGE_ID", "binance"),
        api_key=os.getenv("SHORT_BOT_API_KEY", ""),
        api_secret=os.getenv("SHORT_BOT_API_SECRET", ""),
        sandbox=os.getenv("SANDBOX", "true").lower() == "true",
        paper_trading=os.getenv("PAPER_TRADING", "true").lower() == "true",
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379"),
        heartbeat_interval=3,
        max_retries=3,
        retry_base_delay=1.0
    )


if __name__ == "__main__":
    async def main():
        config = create_short_bot_config()
        bot = ShortTradingBot(config)
        await bot.start()
    
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShort bot stopped by user")
