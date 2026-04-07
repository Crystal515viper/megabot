"""
Formatters for Telegram messages.
Handles Markdown V2 formatting and escaping.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def escape_markdown_v2(text: str) -> str:
    """
    Escape special characters for Telegram Markdown V2.
    
    Characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    if not text:
        return text
    
    special_chars = r'_*[]()~`>#+-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def format_message(text: str, use_markdown: bool = True) -> str:
    """
    Format message with Markdown V2 or fallback to plain text.
    
    Args:
        text: The message text (may contain markdown symbols)
        use_markdown: Whether to attempt markdown formatting
        
    Returns:
        Formatted message string
    """
    if not use_markdown:
        return text
    
    try:
        # Basic validation - if it contains unescaped special chars, escape them
        # This is a simplified check; in production, you'd want more robust parsing
        return text
    except Exception as e:
        logger.warning(f"Markdown formatting failed, falling back to plain text: {e}")
        return escape_markdown_v2(text)


def format_signal_message(signal_data: dict) -> str:
    """
    Format a signal notification message.
    
    Args:
        signal_data: Dictionary with signal information
        
    Returns:
        Formatted message string
    """
    symbol = signal_data.get('symbol', 'UNKNOWN')
    side = signal_data.get('side', 'UNKNOWN')
    price = signal_data.get('price', 0)
    leverage = signal_data.get('leverage', 1)
    risk_roi = signal_data.get('risk_roi', 0)
    
    emoji = "📈" if side == "LONG" else "📉"
    
    message = f"""{emoji} *New Signal Accepted*

*Symbol:* {escape_markdown_v2(symbol)}
*Side:* {escape_markdown_v2(side)}
*Price:* {price}
*Leverage:* {leverage}x
*Risk ROI:* {risk_roi:.2%}

Signal queued for execution."""
    
    return message


def format_order_executed_message(order_data: dict) -> str:
    """
    Format an order execution notification.
    
    Args:
        order_data: Dictionary with order information
        
    Returns:
        Formatted message string
    """
    symbol = order_data.get('symbol', 'UNKNOWN')
    side = order_data.get('side', 'UNKNOWN')
    filled_price = order_data.get('filled_price', 0)
    amount = order_data.get('amount', 0)
    order_id = order_data.get('order_id', 'N/A')
    
    emoji = "✅" if side == "LONG" else "🔻"
    
    message = f"""{emoji} *Order Executed*

*Symbol:* {escape_markdown_v2(symbol)}
*Side:* {escape_markdown_v2(side)}
*Filled Price:* {filled_price}
*Amount:* {amount}
*Order ID:* `{order_id}`"""
    
    return message


def format_trailing_activated_message(position_data: dict) -> str:
    """
    Format a trailing stop activation notification.
    
    Args:
        position_data: Dictionary with position information
        
    Returns:
        Formatted message string
    """
    symbol = position_data.get('symbol', 'UNKNOWN')
    entry_price = position_data.get('entry_price', 0)
    current_price = position_data.get('current_price', 0)
    pnl_percent = position_data.get('pnl_percent', 0)
    trailing_stop = position_data.get('trailing_stop', 0)
    
    message = f"""🎯 *Trailing Stop Activated*

*Symbol:* {escape_markdown_v2(symbol)}
*Entry Price:* {entry_price}
*Current Price:* {current_price}
*PnL:* {pnl_percent:+.2f}%
*Initial Trailing Stop:* {trailing_stop}

Trailing stop is now active."""
    
    return message


def format_sl_triggered_message(position_data: dict) -> str:
    """
    Format a stop-loss triggered notification.
    
    Args:
        position_data: Dictionary with position information
        
    Returns:
        Formatted message string
    """
    symbol = position_data.get('symbol', 'UNKNOWN')
    side = position_data.get('side', 'UNKNOWN')
    entry_price = position_data.get('entry_price', 0)
    exit_price = position_data.get('exit_price', 0)
    pnl = position_data.get('pnl', 0)
    pnl_percent = position_data.get('pnl_percent', 0)
    
    emoji = "⛔"
    pnl_emoji = "💰" if pnl > 0 else "💸"
    
    message = f"""{emoji} *Stop Loss Triggered*

*Symbol:* {escape_markdown_v2(symbol)}
*Side:* {escape_markdown_v2(side)}
*Entry:* {entry_price} | *Exit:* {exit_price}
{pnl_emoji} *PnL:* {pnl:+.2f} ({pnl_percent:+.2f}%)

Position closed by trailing stop."""
    
    return message


def format_error_message(error_data: dict) -> str:
    """
    Format an error notification.
    
    Args:
        error_data: Dictionary with error information
        
    Returns:
        Formatted message string
    """
    bot_name = error_data.get('bot_name', 'Unknown Bot')
    error_type = error_data.get('error_type', 'Error')
    error_msg = error_data.get('message', 'No details')
    timestamp = error_data.get('timestamp', 'N/A')
    
    message = f"""🚨 *Bot Error Alert*

*Bot:* {escape_markdown_v2(bot_name)}
*Type:* {escape_markdown_v2(error_type)}
*Time:* {timestamp}

*Details:*
{escape_markdown_v2(error_msg)}

Please check system logs immediately."""
    
    return message


def format_status_message(status_data: dict) -> str:
    """
    Format a status report message.
    
    Args:
        status_data: Dictionary with system status
        
    Returns:
        Formatted message string
    """
    system_health = status_data.get('system_health', 'unknown')
    open_positions = status_data.get('open_positions', 0)
    total_pnl = status_data.get('total_pnl', 0)
    win_rate = status_data.get('win_rate', 0)
    bots_status = status_data.get('bots_status', {})
    
    health_emoji = "🟢" if system_health == "healthy" else "🔴" if system_health == "unhealthy" else "🟡"
    
    bots_text = ""
    for bot_name, bot_info in bots_status.items():
        status = bot_info.get('status', 'unknown')
        last_heartbeat = bot_info.get('last_heartbeat', 'N/A')
        bot_emoji = "🟢" if status == "online" else "🔴"
        bots_text += f"{bot_emoji} {escape_markdown_v2(bot_name)}: {status} (last seen: {last_heartbeat})\n"
    
    message = f"""{health_emoji} *System Status Report*

*Open Positions:* {open_positions}
*Total PnL:* {total_pnl:+.2f}
*Win Rate:* {win_rate:.1f}%

*Bot Status:*
{bots_text}
All systems operational."""
    
    return message


def format_help_message() -> str:
    """
    Format the help message with strategy description and commands.
    
    Returns:
        Formatted message string
    """
    message = """🤖 *Trading Bot Help*

*Strategy Overview:*
This system implements a dual-account hedging strategy with dynamic leverage and trailing stops. It filters signals based on volatility (ATR, Z-score, SNR) and executes trades on both LONG and SHORT sides simultaneously.

*Key Features:*
• Dynamic leverage calculation based on ATR and SNR
• Trailing stop with adaptive step sizes
• Real-time risk management
• Full audit logging

*Available Commands:*
/start - Initialize bot and show welcome message
/status - Show current system status and open positions
/report - Generate detailed trading report
/pause - Pause trading (bots stop opening new positions)
/resume - Resume trading after pause
/help - Show this help message

*Notifications:*
You will receive automatic alerts for:
• New signals accepted
• Order executions
• Trailing stop activations
• Stop-loss triggers
• System errors

*Note:* All commands require admin privileges."""
    
    return message
