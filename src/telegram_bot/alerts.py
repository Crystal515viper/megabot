"""
Telegram Bot Alerts System.
Sends automatic notifications for trading events.
Uses asyncio.Queue for rate limiting (30 msg/sec).
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from telegram import Bot
from telegram.error import TelegramError, RetryAfter

from .formatters import (
    format_signal_message,
    format_order_executed_message,
    format_trailing_activated_message,
    format_sl_triggered_message,
    format_error_message,
)

logger = logging.getLogger(__name__)


class AlertQueue:
    """
    Rate-limited message queue for Telegram alerts.
    
    Implements a queue with rate limiting to avoid hitting Telegram's
    30 messages per second limit.
    """
    
    def __init__(self, bot: Bot, chat_ids: list, max_retries: int = 3):
        """
        Initialize the alert queue.
        
        Args:
            bot: Telegram bot instance
            chat_ids: List of chat IDs to send alerts to
            max_retries: Maximum number of retry attempts
        """
        self.bot = bot
        self.chat_ids = chat_ids
        self.max_retries = max_retries
        self.queue: asyncio.Queue = asyncio.Queue()
        self.is_running = False
        self.worker_task: Optional[asyncio.Task] = None
        
    async def start(self):
        """Start the queue worker."""
        if not self.is_running:
            self.is_running = True
            self.worker_task = asyncio.create_task(self._worker())
            logger.info("Alert queue worker started")
    
    async def stop(self):
        """Stop the queue worker gracefully."""
        self.is_running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Alert queue worker stopped")
    
    async def add_alert(self, message: str, priority: int = 0):
        """
        Add an alert to the queue.
        
        Args:
            message: The message to send
            priority: Priority level (higher = sent first)
        """
        await self.queue.put((priority, message))
        logger.debug(f"Alert added to queue (priority={priority})")
    
    async def _worker(self):
        """
        Queue worker that processes messages with rate limiting.
        
        Sends messages one by one with a small delay to respect rate limits.
        """
        while self.is_running:
            try:
                # Get message from queue (wait up to 1 second)
                try:
                    priority, message = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Send to all chat IDs
                for chat_id in self.chat_ids:
                    await self._send_with_retry(chat_id, message)
                
                # Small delay to respect rate limits (30 msg/sec = ~33ms per msg)
                # Using 50ms to be safe
                await asyncio.sleep(0.05)
                
                self.queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in alert queue worker: {e}")
                await asyncio.sleep(1.0)
    
    async def _send_with_retry(self, chat_id: int, message: str):
        """
        Send a message with retry logic.
        
        Args:
            chat_id: Target chat ID
            message: Message to send
        """
        for attempt in range(self.max_retries):
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='MarkdownV2'
                )
                logger.debug(f"Alert sent to chat {chat_id}")
                return
                
            except RetryAfter as e:
                # Telegram rate limit exceeded
                wait_time = e.retry_after
                logger.warning(f"Rate limit hit, waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                
            except TelegramError as e:
                if attempt == self.max_retries - 1:
                    logger.error(f"Failed to send alert after {self.max_retries} attempts: {e}")
                    # Fallback to plain text
                    try:
                        await self.bot.send_message(
                            chat_id=chat_id,
                            text=message.replace('*', '').replace('_', '').replace('`', ''),
                            parse_mode=None
                        )
                    except Exception as fallback_error:
                        logger.error(f"Fallback also failed: {fallback_error}")
                else:
                    # Exponential backoff
                    wait_time = (2 ** attempt) * 0.5
                    logger.warning(f"Telegram error, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)


class AlertManager:
    """
    Manages all alert notifications for the trading system.
    
    Provides methods to send different types of alerts:
    - Signal accepted
    - Order executed
    - Trailing stop activated
    - Stop-loss triggered
    - Bot errors
    """
    
    def __init__(self, bot: Bot, chat_ids: list, config: Dict[str, bool]):
        """
        Initialize the alert manager.
        
        Args:
            bot: Telegram bot instance
            chat_ids: List of chat IDs to notify
            config: Configuration flags for different alert types
        """
        self.bot = bot
        self.chat_ids = chat_ids
        self.config = config
        self.queue = AlertQueue(bot, chat_ids)
        
    async def start(self):
        """Start the alert system."""
        await self.queue.start()
        logger.info("Alert manager started")
    
    async def stop(self):
        """Stop the alert system gracefully."""
        await self.queue.stop()
        logger.info("Alert manager stopped")
    
    async def notify_signal_accepted(self, signal_data: Dict[str, Any]):
        """
        Send notification when a signal is accepted.
        
        Args:
            signal_data: Signal information dictionary
        """
        if not self.config.get('NOTIFY_ON_SIGNAL', True):
            logger.debug("Signal notifications disabled")
            return
        
        message = format_signal_message(signal_data)
        await self.queue.add_alert(message, priority=1)
        logger.info(f"Signal alert queued for {signal_data.get('symbol', 'UNKNOWN')}")
    
    async def notify_order_executed(self, order_data: Dict[str, Any]):
        """
        Send notification when an order is executed.
        
        Args:
            order_data: Order information dictionary
        """
        if not self.config.get('NOTIFY_ON_ORDER', True):
            logger.debug("Order notifications disabled")
            return
        
        message = format_order_executed_message(order_data)
        await self.queue.add_alert(message, priority=1)
        logger.info(f"Order execution alert queued for {order_data.get('symbol', 'UNKNOWN')}")
    
    async def notify_trailing_activated(self, position_data: Dict[str, Any]):
        """
        Send notification when trailing stop is activated.
        
        Args:
            position_data: Position information dictionary
        """
        if not self.config.get('NOTIFY_ON_TRAILING', True):
            logger.debug("Trailing notifications disabled")
            return
        
        message = format_trailing_activated_message(position_data)
        await self.queue.add_alert(message, priority=2)
        logger.info(f"Trailing activation alert queued for {position_data.get('symbol', 'UNKNOWN')}")
    
    async def notify_sl_triggered(self, position_data: Dict[str, Any]):
        """
        Send notification when stop-loss is triggered.
        
        Args:
            position_data: Position information dictionary
        """
        if not self.config.get('NOTIFY_ON_SL', True):
            logger.debug("SL notifications disabled")
            return
        
        message = format_sl_triggered_message(position_data)
        await self.queue.add_alert(message, priority=3)
        logger.info(f"SL trigger alert queued for {position_data.get('symbol', 'UNKNOWN')}")
    
    async def notify_error(self, error_data: Dict[str, Any]):
        """
        Send notification when a bot error occurs.
        
        Args:
            error_data: Error information dictionary
        """
        # Always send error notifications regardless of config
        message = format_error_message(error_data)
        await self.queue.add_alert(message, priority=10)  # High priority
        logger.error(f"Error alert queued: {error_data.get('error_type', 'Unknown')}")
    
    async def send_custom_message(self, message: str, priority: int = 0):
        """
        Send a custom message.
        
        Args:
            message: The message to send
            priority: Priority level
        """
        await self.queue.add_alert(message, priority=priority)


def create_alert_manager(bot_token: str, chat_ids: list, config: Dict[str, bool]) -> AlertManager:
    """
    Factory function to create an AlertManager instance.
    
    Args:
        bot_token: Telegram bot token
        chat_ids: List of chat IDs to notify
        config: Configuration flags
        
    Returns:
        AlertManager instance
    """
    bot = Bot(token=bot_token)
    return AlertManager(bot, chat_ids, config)


# Example usage and message templates
if __name__ == "__main__":
    # This is a demonstration of message formats
    print("=== Telegram Alert Message Templates ===\n")
    
    # Signal message example
    signal_data = {
        'symbol': 'BTCUSDT',
        'side': 'LONG',
        'price': 45000.0,
        'leverage': 5,
        'risk_roi': 0.02
    }
    print("Signal Accepted:")
    print(format_signal_message(signal_data))
    print("\n" + "="*50 + "\n")
    
    # Order executed example
    order_data = {
        'symbol': 'ETHUSDT',
        'side': 'SHORT',
        'filled_price': 3200.5,
        'amount': 0.5,
        'order_id': '12345678'
    }
    print("Order Executed:")
    print(format_order_executed_message(order_data))
    print("\n" + "="*50 + "\n")
    
    # Trailing activated example
    position_data = {
        'symbol': 'BTCUSDT',
        'entry_price': 45000.0,
        'current_price': 46800.0,
        'pnl_percent': 4.0,
        'trailing_stop': 45900.0
    }
    print("Trailing Activated:")
    print(format_trailing_activated_message(position_data))
    print("\n" + "="*50 + "\n")
    
    # SL triggered example
    sl_data = {
        'symbol': 'ETHUSDT',
        'side': 'LONG',
        'entry_price': 3200.0,
        'exit_price': 3150.0,
        'pnl': -25.0,
        'pnl_percent': -1.56
    }
    print("SL Triggered:")
    print(format_sl_triggered_message(sl_data))
    print("\n" + "="*50 + "\n")
    
    # Error message example
    error_data = {
        'bot_name': 'Bot-Long',
        'error_type': 'ConnectionError',
        'message': 'Failed to connect to exchange API after 3 retries',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    print("Error Alert:")
    print(format_error_message(error_data))
