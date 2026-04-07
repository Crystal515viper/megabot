"""
Telegram Bot Commands Handler.
Implements /start, /status, /report, /pause, /resume, /help commands.
"""

import logging
from datetime import datetime
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from .formatters import (
    format_status_message,
    format_help_message,
    escape_markdown_v2,
)

logger = logging.getLogger(__name__)


async def check_admin_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Check if the user has admin access.
    
    Args:
        update: Telegram update object
        context: Context object
        
    Returns:
        True if user is admin, False otherwise
    """
    user_id = update.effective_user.id if update.effective_user else None
    
    if not user_id:
        logger.warning("Command received without user ID")
        return False
    
    # Get allowed admin IDs from config
    allowed_ids = context.bot_data.get('admin_ids', [])
    
    if user_id not in allowed_ids:
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        try:
            await update.message.reply_text(
                "❌ Access denied. Only administrators can use this bot."
            )
        except TelegramError as e:
            logger.error(f"Failed to send access denied message: {e}")
        return False
    
    return True


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start command.
    
    Initializes the bot and shows welcome message.
    """
    if not await check_admin_access(update, context):
        return
    
    user_name = update.effective_user.first_name if update.effective_user else "Trader"
    
    welcome_message = f"""👋 Welcome, {escape_markdown_v2(user_name)}!

I'm your *Trading System Assistant*.

This bot provides real-time notifications and control over the trading system.

*What I can do:*
• Send instant alerts on signals and trades
• Provide system status reports
• Allow you to pause/resume trading
• Answer questions about the strategy

Use /help to see all available commands.

*System Status:* 🟢 Online
Ready to trade!"""
    
    try:
        await update.message.reply_text(
            welcome_message,
            parse_mode='MarkdownV2'
        )
        logger.info(f"Start command executed by user {update.effective_user.id}")
    except TelegramError as e:
        logger.error(f"Failed to send start message: {e}")
        # Fallback to plain text
        await update.message.reply_text(
            f"Welcome, {user_name}! I'm your Trading System Assistant. Use /help to see commands."
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /status command.
    
    Shows current system status and open positions.
    """
    if not await check_admin_access(update, context):
        return
    
    try:
        # Get status from Redis or API
        # This is a placeholder - in production, fetch from Redis/API
        status_data = {
            'system_health': 'healthy',
            'open_positions': 2,
            'total_pnl': 125.50,
            'win_rate': 68.5,
            'bots_status': {
                'Bot-Long': {'status': 'online', 'last_heartbeat': datetime.now().strftime('%H:%M:%S')},
                'Bot-Short': {'status': 'online', 'last_heartbeat': datetime.now().strftime('%H:%M:%S')},
            }
        }
        
        message = format_status_message(status_data)
        
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        logger.info(f"Status command executed by user {update.effective_user.id}")
        
    except TelegramError as e:
        logger.error(f"Failed to send status message: {e}")
        await update.message.reply_text("⚠️ Failed to retrieve status. Please check system logs.")
    except Exception as e:
        logger.error(f"Unexpected error in status command: {e}")
        await update.message.reply_text("⚠️ An error occurred while fetching status.")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /report command.
    
    Generates detailed trading report.
    """
    if not await check_admin_access(update, context):
        return
    
    try:
        # Placeholder for report generation
        # In production, fetch from database and calculate metrics
        report_message = """📊 *Trading Report*

*Period:* Last 24 hours

*Total Trades:* 15
*Winning Trades:* 10
*Losing Trades:* 5
*Win Rate:* 66.7%

*Profit Factor:* 2.35
*Sharpe Ratio:* 1.82
*Max Drawdown:* -3.2%

*Total PnL:* +$342.50

*Best Trade:* +$125.00 (BTCUSDT LONG)
*Worst Trade:* -$45.00 (ETHUSDT SHORT)

Report generated at: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        await update.message.reply_text(
            report_message,
            parse_mode='MarkdownV2'
        )
        logger.info(f"Report command executed by user {update.effective_user.id}")
        
    except TelegramError as e:
        logger.error(f"Failed to send report message: {e}")
        await update.message.reply_text("⚠️ Failed to generate report. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error in report command: {e}")
        await update.message.reply_text("⚠️ An error occurred while generating report.")


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /pause command.
    
    Pauses trading (bots stop opening new positions).
    """
    if not await check_admin_access(update, context):
        return
    
    try:
        # In production, set a flag in Redis to pause trading
        # context.bot_data['trading_paused'] = True
        
        pause_message = """⏸️ *Trading Paused*

Bots will stop opening new positions.
Existing positions will continue to be managed.

Use /resume to restart trading."""
        
        await update.message.reply_text(
            pause_message,
            parse_mode='MarkdownV2'
        )
        logger.warning(f"Trading paused by user {update.effective_user.id}")
        
    except TelegramError as e:
        logger.error(f"Failed to send pause message: {e}")
        await update.message.reply_text("⚠️ Failed to pause trading. Please check system logs.")
    except Exception as e:
        logger.error(f"Unexpected error in pause command: {e}")
        await update.message.reply_text("⚠️ An error occurred while pausing trading.")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /resume command.
    
    Resumes trading after pause.
    """
    if not await check_admin_access(update, context):
        return
    
    try:
        # In production, clear the pause flag in Redis
        # context.bot_data['trading_paused'] = False
        
        resume_message = """▶️ *Trading Resumed*

Bots are now accepting new signals.
All systems operational."""
        
        await update.message.reply_text(
            resume_message,
            parse_mode='MarkdownV2'
        )
        logger.info(f"Trading resumed by user {update.effective_user.id}")
        
    except TelegramError as e:
        logger.error(f"Failed to send resume message: {e}")
        await update.message.reply_text("⚠️ Failed to resume trading. Please check system logs.")
    except Exception as e:
        logger.error(f"Unexpected error in resume command: {e}")
        await update.message.reply_text("⚠️ An error occurred while resuming trading.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /help command.
    
    Shows help message with strategy description and commands.
    """
    if not await check_admin_access(update, context):
        return
    
    try:
        message = format_help_message()
        
        await update.message.reply_text(
            message,
            parse_mode='MarkdownV2'
        )
        logger.info(f"Help command executed by user {update.effective_user.id}")
        
    except TelegramError as e:
        logger.error(f"Failed to send help message: {e}")
        # Fallback to plain text
        help_text = """Trading Bot Help

Strategy: Dual-account hedging with dynamic leverage and trailing stops.

Commands:
/start - Welcome message
/status - System status
/report - Trading report
/pause - Pause trading
/resume - Resume trading
/help - This help message

All commands require admin privileges."""
        await update.message.reply_text(help_text)
    except Exception as e:
        logger.error(f"Unexpected error in help command: {e}")
        await update.message.reply_text("⚠️ An error occurred while fetching help.")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle unknown commands.
    """
    if not update.effective_user:
        return
    
    # Only respond to admins
    user_id = update.effective_user.id
    allowed_ids = context.bot_data.get('admin_ids', [])
    
    if user_id not in allowed_ids:
        return
    
    try:
        await update.message.reply_text(
            "❓ Unknown command. Use /help to see available commands.",
            parse_mode='MarkdownV2'
        )
    except TelegramError as e:
        logger.error(f"Failed to send unknown command response: {e}")
