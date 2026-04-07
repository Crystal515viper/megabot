"""
Telegram Bot Main Entry Point.
Initializes the bot, sets up command handlers, and starts the alert system.
"""

import asyncio
import logging
import signal
from typing import List, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from .commands import (
    start_command,
    status_command,
    report_command,
    pause_command,
    resume_command,
    help_command,
    unknown_command,
)
from .alerts import AlertManager, create_alert_manager
from .formatters import format_help_message

logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Main Telegram Bot class for the trading system.
    
    Handles initialization, command routing, and graceful shutdown.
    """
    
    def __init__(
        self,
        token: str,
        admin_ids: List[int],
        chat_ids: List[int],
        config: dict,
    ):
        """
        Initialize the Telegram bot.
        
        Args:
            token: Telegram bot token from .env
            admin_ids: List of allowed admin user IDs
            chat_ids: List of chat IDs to send alerts to
            config: Configuration dictionary with notification flags
        """
        self.token = token
        self.admin_ids = admin_ids
        self.chat_ids = chat_ids
        self.config = config
        
        self.application: Optional[Application] = None
        self.alert_manager: Optional[AlertManager] = None
        self.is_running = False
        
    async def initialize(self):
        """Initialize the bot application and alert manager."""
        logger.info("Initializing Telegram bot...")
        
        # Create the application
        self.application = (
            Application.builder()
            .token(self.token)
            .build()
        )
        
        # Store admin IDs in bot_data for access in handlers
        self.application.bot_data['admin_ids'] = self.admin_ids
        
        # Register command handlers
        self.application.add_handler(CommandHandler("start", start_command))
        self.application.add_handler(CommandHandler("status", status_command))
        self.application.add_handler(CommandHandler("report", report_command))
        self.application.add_handler(CommandHandler("pause", pause_command))
        self.application.add_handler(CommandHandler("resume", resume_command))
        self.application.add_handler(CommandHandler("help", help_command))
        
        # Handle unknown commands
        self.application.add_handler(
            MessageHandler(filters.COMMAND & ~filters.Regex("^/(start|status|report|pause|resume|help)$"), unknown_command)
        )
        
        # Initialize alert manager
        self.alert_manager = create_alert_manager(self.token, self.chat_ids, self.config)
        
        logger.info("Telegram bot initialized successfully")
    
    async def start(self):
        """Start the bot and alert system."""
        if not self.application:
            await self.initialize()
        
        logger.info("Starting Telegram bot...")
        
        # Start alert manager
        await self.alert_manager.start()
        
        # Start the bot polling
        self.is_running = True
        await self.application.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
        
        logger.info("Telegram bot started successfully")
    
    async def stop(self):
        """Stop the bot and alert system gracefully."""
        logger.info("Stopping Telegram bot...")
        
        self.is_running = False
        
        # Stop the updater
        if self.application and self.application.updater:
            await self.application.updater.stop()
        
        # Stop alert manager
        if self.alert_manager:
            await self.alert_manager.stop()
        
        logger.info("Telegram bot stopped successfully")
    
    async def run_forever(self):
        """Run the bot until shutdown signal is received."""
        await self.start()
        
        # Wait until shutdown
        while self.is_running:
            await asyncio.sleep(1)
    
    def get_alert_manager(self) -> Optional[AlertManager]:
        """Get the alert manager instance."""
        return self.alert_manager


async def main():
    """Main entry point for the Telegram bot."""
    import os
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    # Get configuration from environment
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    admin_ids_str = os.getenv('TELEGRAM_ADMIN_IDS', '')
    chat_ids_str = os.getenv('TELEGRAM_CHAT_IDS', '')
    
    # Parse IDs
    admin_ids = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
    chat_ids = [int(x.strip()) for x in chat_ids_str.split(',') if x.strip()]
    
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment")
        return
    
    if not admin_ids:
        logger.warning("No admin IDs configured. Bot will not respond to commands.")
    
    if not chat_ids:
        logger.warning("No chat IDs configured. Alerts will not be sent.")
        chat_ids = admin_ids  # Fallback to admin IDs
    
    # Configuration flags
    config = {
        'NOTIFY_ON_SIGNAL': os.getenv('NOTIFY_ON_SIGNAL', 'True').lower() == 'true',
        'NOTIFY_ON_ORDER': os.getenv('NOTIFY_ON_ORDER', 'True').lower() == 'true',
        'NOTIFY_ON_TRAILING': os.getenv('NOTIFY_ON_TRAILING', 'True').lower() == 'true',
        'NOTIFY_ON_SL': os.getenv('NOTIFY_ON_SL', 'True').lower() == 'true',
    }
    
    # Create bot instance
    bot = TelegramBot(token, admin_ids, chat_ids, config)
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()
    
    def signal_handler(sig):
        logger.info(f"Received signal {sig}, shutting down...")
        shutdown_event.set()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
    
    try:
        # Initialize and start bot
        await bot.initialize()
        
        # Run bot in background task
        bot_task = asyncio.create_task(bot.run_forever())
        
        # Wait for shutdown signal
        await shutdown_event.wait()
        
        # Graceful shutdown
        await bot.stop()
        bot_task.cancel()
        
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
        
        logger.info("Telegram bot shutdown complete")
        
    except Exception as e:
        logger.error(f"Fatal error in Telegram bot: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run the bot
    asyncio.run(main())
