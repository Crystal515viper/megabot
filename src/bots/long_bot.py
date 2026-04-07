"""
Long Trading Bot.

Specialized bot for LONG positions.
Listens to queue:signals_long and executes long trades.
"""

import os
import asyncio
from loguru import logger

from src.bots.base_bot import BaseTradingBot, BotConfig


class LongTradingBot(BaseTradingBot):
    """
    Long-side trading bot.
    
    Subscribes to queue:signals_long and executes BUY/LONG orders.
    """
    
    def __init__(self, config: BotConfig):
        # Override queue settings for LONG
        config.queue_name = "queue:signals_long"
        config.heartbeat_key = "bot:long:heartbeat"
        config.account_side = "LONG"
        
        super().__init__(config)
        logger.info("[LongBot] Initialized for LONG trading")
    
    def get_queue_name(self) -> str:
        """Return LONG queue name."""
        return "queue:signals_long"


def create_long_bot_config() -> BotConfig:
    """
    Create bot configuration from environment variables.
    
    Expected ENV vars:
    - LONG_BOT_API_KEY
    - LONG_BOT_API_SECRET
    - EXCHANGE_ID (default: binance)
    - PAPER_TRADING (default: True)
    - REDIS_URL
    """
    return BotConfig(
        bot_name="bot-long",
        account_side="LONG",
        exchange_id=os.getenv("EXCHANGE_ID", "binance"),
        api_key=os.getenv("LONG_BOT_API_KEY", ""),
        api_secret=os.getenv("LONG_BOT_API_SECRET", ""),
        sandbox=os.getenv("SANDBOX", "true").lower() == "true",
        paper_trading=os.getenv("PAPER_TRADING", "true").lower() == "true",
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379"),
        heartbeat_interval=3,
        max_retries=3,
        retry_base_delay=1.0
    )


if __name__ == "__main__":
    async def main():
        config = create_long_bot_config()
        bot = LongTradingBot(config)
        await bot.start()
    
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nLong bot stopped by user")
