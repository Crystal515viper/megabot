#!/usr/bin/env python3
"""
Simplified Scanner v8 - Aggressive momentum trading
"""

import math
import os
import json
import time
import hmac
import hashlib
import requests
from datetime import datetime
from signal_filter import filter_signal
import config  # Import config for LEVERAGE, MIN_PRICE_CHANGE, etc.
import strategy_improvements as si  # NEW: Strategy improvements module

# === LOAD FROM ENV FILE ===

# Import advanced modules
try:
    import advanced_analysis as aa
    import error_handling as eh
    ADVANCED_ANALYSIS_AVAILABLE = True
except ImportError as e:
    ADVANCED_ANALYSIS_AVAILABLE = False
    print(f"Warning: Advanced modules not available: {e}")

# Only load from the same directory as the script
script_dir = os.path.dirname(os.path.abspath(__file__))
env_file = os.path.join(script_dir, '.env')

if env_file and os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

# === LOAD CONFIG FROM config.py ===
try:
    from config import *
except ImportError:
    pass

# Load delisting blocklist
try:
    from delisting_monitor import is_token_blocked, get_blocklist, check_binance_delist_announcements
    DELISTING_CHECK = True
except ImportError:
    DELISTING_CHECK = False

# Default ATR multipliers if not loaded from config
try:
    ATR_MULTIPLIER_SL_HIGH
except NameError:
    ATR_MULTIPLIER_SL_HIGH = 2.0
try:
    ATR_MULTIPLIER_TP_HIGH
except NameError:
    ATR_MULTIPLIER_TP_HIGH = 8.0  # 8x ATR for 1:4 ratio
try:
    ATR_MULTIPLIER_SL_NORMAL
except NameError:
    ATR_MULTIPLIER_SL_NORMAL = 2.0  # Match SL to HIGH
try:
    ATR_MULTIPLIER_TP_NORMAL
except NameError:
    ATR_MULTIPLIER_TP_NORMAL = 8.0  # 8x ATR for 1:4 ratio
try:
    ATR_MULTIPLIER_SL_LOW
except NameError:
    ATR_MULTIPLIER_SL_LOW = 1.0
try:
    ATR_MULTIPLIER_TP_LOW
except NameError:
    ATR_MULTIPLIER_TP_LOW = 6.0  # 6x ATR for 1:4 ratio

# === CONFIG ===
API_KEY = os.environ.get('BINANCE_API_KEY', '')
SECRET = os.environ.get('BINANCE_SECRET', '')
from binance_urls import futures_base_url, spot_sapi_base_url
import trade_logger
import signals_table
import position_tags

BASE_URL = futures_base_url()
BASE_URL_SPOT = spot_sapi_base_url()

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHANNEL = os.environ.get('TELEGRAM_CHANNEL', '')
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY', '')

# Leverage from config.py
LEVERAGE = config.LEVERAGE  # Now uses 20x from config

# === API HELPERS ===
def get_signature(params):
    return hmac.new(SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()

def binance_get(url, params=None):
    if params:
        params['timestamp'] = int(time.time() * 1000)
        params['signature'] = get_signature('&'.join(f'{k}={v}' for k, v in params.items()))
    headers = {'X-MBX-APIKEY': API_KEY}
    r = requests.get(url, params=params, headers=headers, timeout=15)
    return r.json()

def binance_post(url, params):
    params['timestamp'] = int(time.time() * 1000)
    params['signature'] = get_signature('&'.join(f'{k}={v}' for k, v in params.items()))
    headers = {'X-MBX-APIKEY': API_KEY}
    r = requests.post(url, data=params, headers=headers, timeout=15)
    return r.json()

# === GET DATA ===
def get_balance():
    """Return totalMarginBalance (includes unrealized PnL)"""
    ts = int(time.time() * 1000)
    params = "timestamp={}".format(ts)
    sig = get_signature(params)
    r = requests.get(f"{BASE_URL}/fapi/v3/account?{params}&signature={sig}",
                     headers={"X-MBX-APIKEY": API_KEY}, timeout=15)
    if r:
        try:
            return float(r.json().get('totalMarginBalance', 0))
        except:
            return 0

def get_positions():
    ts = int(time.time() * 1000)
    params = "timestamp={}".format(ts)
    sig = get_signature(params)
    r = requests.get(f"{BASE_URL}/fapi/v3/account?{params}&signature={sig}",
                     headers={"X-MBX-APIKEY": API_KEY}, timeout=15)
    if r:
        return [p for p in r.json().get('positions', []) if float(p.get('positionAmt', 0)) != 0]
    return []

def cleanup_cache():
    """Clean up old cache entries"""
    import time
    now = time.time()
    cutoff = 86400  # 24 hours
    
    # Clean .recently_closed
    try:
        with open('.recently_closed', 'r') as f:
            lines = f.readlines()
        valid = []
        for line in lines:
            parts = line.strip().split(',')
            if len(parts) >= 2:
                sym, ts = parts[0], int(parts[1])
                if now - ts < cutoff:
                    valid.append(line.strip())
        with open('.recently_closed', 'w') as f:
            for line in valid:
                f.write(line + '\n')
    except:
        pass
    
    # Clear .posted_signals to allow re-posts
    try:
        open('.posted_signals', 'w').close()
    except:
        pass

# Cleanup on startup
cleanup_cache()

# ── AUTO-CLEANUP HANGING ORDERS ─────────────────────────────────────
# Check for TP/SL orders without positions and cancel them
def cleanup_hanging_orders():
    try:
        # Get positions
        ts = int(time.time() * 1000)
        params = f'timestamp={ts}'
        sig = get_signature(params)
        r = requests.get(f'{BASE_URL}/fapi/v2/positionRisk?{params}&signature={sig}',
                        headers={"X-MBX-APIKEY": API_KEY}, timeout=10)
        position_symbols = set()
        if r.status_code == 200:
            for p in r.json():
                if float(p.get('positionAmt', 0)) != 0:
                    position_symbols.add(p.get('symbol'))
        
        # Get algo orders
        ts = int(time.time() * 1000)
        params = f'timestamp={ts}'
        sig = get_signature(params)
        r = requests.get(f'{BASE_URL}/fapi/v1/algoOrder?{params}&signature={sig}',
                        headers={"X-MBX-APIKEY": API_KEY}, timeout=10)
        orders = r.json().get('orders', []) if isinstance(r.json(), dict) else []
        
        # Cancel hanging
        for order in orders:
            symbol = order.get('symbol')
            if symbol and symbol not in position_symbols:
                order_id = order.get('algoId') or order.get('orderId')
                ts = int(time.time() * 1000)
                params = f'symbol={symbol}&algoId={order_id}&timestamp={ts}'
                sig = get_signature(params)
                r = requests.delete(f'{BASE_URL}/fapi/v1/algoOrder?{params}&signature={sig}',
                                  headers={"X-MBX-APIKEY": API_KEY}, timeout=10)
                if r.status_code == 200:
                    print(f"[CLEANUP] Cancelled hanging order: {symbol} (ID: {order_id})")
    except Exception as e:
        print(f"[CLEANUP] Error: {e}")

# Run cleanup on startup
cleanup_hanging_orders()
# ────────────────────────────────────────────────────────────────────────

def get_24h_tickers():
    return binance_get(f'{BASE_URL}/fapi/v1/ticker/24hr')

def get_open_interest(symbol):
    """Get current Open Interest for a symbol"""
    try:
        url = f'{BASE_URL}/fapi/v1/openInterest?symbol={symbol}'
        r = requests.get(url, timeout=10)
        data = r.json()
        return float(data.get('openInterest', 0))
    except:
        return 0

def get_oi_change(symbol, limit=5):
    """Get OI change over recent candles - returns percentage change"""
    try:
        url = f'{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval=1h&limit={limit+1}'
        r = requests.get(url, timeout=10)
        candles = r.json()
        
        # Get OI for each hour
        oi_values = []
        for i in range(1, len(candles)):
            # Use volume as proxy for OI (not exact but related)
            vol = float(candles[i][5])  # volume
            oi_values.append(vol)
        
        if len(oi_values) < 2:
            return 0
        
        # Calculate change
        current = oi_values[-1]
        previous = sum(oi_values[:-1]) / len(oi_values[:-1])
        
        if previous == 0:
            return 0
        
        return ((current - previous) / previous) * 100
    except:
        return 0

def get_oi_history(symbol, period='1h', limit=24):
    """Get OI history - more accurate than volume proxy"""
    try:
        url = f'https://futures.binance.com/futures/data/openInterestHist?symbol={symbol.replace("USDT","")}&period={period}&limit={limit}'
        r = requests.get(url, timeout=10)
        data = r.json()
        if data and len(data) > 1:
            # Calculate OI change trend
            oi_values = [float(d['openInterest']) for d in data]
            current = oi_values[-1]
            previous = sum(oi_values[:-1]) / len(oi_values[:-1])
            if previous > 0:
                return {
                    'current': current,
                    'change_pct': ((current - previous) / previous) * 100,
                    'trend': 'up' if current > previous else 'down'
                }
        return {'current': 0, 'change_pct': 0, 'trend': 'neutral'}
    except:
        return {'current': 0, 'change_pct': 0, 'trend': 'neutral'}

def get_mark_price(symbol):
    """Get mark price for more accurate SL/TP"""
    try:
        url = f'{BASE_URL}/fapi/v1/markPrice?symbol={symbol}'
        r = requests.get(url, timeout=10)
        data = r.json()
        return float(data.get('markPrice', 0))
    except:
        return 0

def get_price_v2(symbol):
    """Get price using v2 endpoint - lower latency"""
    try:
        url = f'{BASE_URL}/fapi/v2/ticker/price?symbol={symbol}'
        r = requests.get(url, timeout=10)
        data = r.json()
        return float(data.get('price', 0))
    except:
        return 0

def get_klines(symbol, interval='1h', limit=100):
    url = f'{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}'
    r = requests.get(url, timeout=15)
    return r.json()

def place_order_with_sl_tp(symbol, side, quantity, sl_price, tp_price):
    """Place market order FIRST, then SL (and TP unless SCANNER_USE_TRAIL_EXIT)."""
    ts = int(time.time() * 1000)
    
    # First place the market order
    params = "symbol={}&side={}&type=MARKET&quantity={}&timestamp={}".format(symbol, side, quantity, ts)
    sig = get_signature(params)
    url = f"{BASE_URL}/fapi/v1/order?{params}&signature={sig}"
    headers = {'X-MBX-APIKEY': API_KEY}
    r = requests.post(url, headers=headers, timeout=15)
    result = r.json()
    
    # Only place SL/TP if market order succeeded
    order_id = result.get('orderId')
    if not order_id or str(order_id) == 'N/A':
        return result  # Return early - market order failed, no SL/TP

    # Повторный clamp по фактической цене входа (сигнал считался по last, fill может отличаться).
    avg_px = float(result.get("avgPrice") or 0)
    if avg_px <= 0:
        eq = float(result.get("executedQty") or 0)
        cq = float(result.get("cumQuote") or 0)
        if eq > 0 and cq > 0:
            avg_px = cq / eq
    if sl_price and avg_px > 0:
        d = "LONG" if side == "BUY" else "SHORT"
        sl_price = config.clamp_sl_price_to_leverage(d, avg_px, float(sl_price))

    trail_exit = bool(getattr(config, "SCANNER_USE_TRAIL_EXIT", True))
    if not sl_price:
        return result

    sl_trigger = sl_price

    try:
        info_r = requests.get(f'{BASE_URL}/fapi/v1/exchangeInfo', timeout=10)
        tick_size = 0.00001  # default
        for s in info_r.json().get('symbols', []):
            if s['symbol'] == symbol:
                for f in s.get('filters', []):
                    if f.get('filterType') == 'PRICE_FILTER':
                        tick_size = float(f.get('tickSize', 0.00001))
                break
    except Exception:
        tick_size = 0.00001

    def round_to_tick(price, tick):
        tick_str = f"{tick:.10f}".rstrip('0')
        decimals = len(tick_str.split('.')[1]) if '.' in tick_str else 0
        return float(f"{price:.{decimals}f}")

    sl_trigger_rounded = round_to_tick(sl_trigger, tick_size)

    sl_side = "SELL" if side == "BUY" else "BUY"
    sl_params = "symbol={}&side={}&type=STOP_MARKET&orderType=STOP_MARKET&algoType=CONDITIONAL&quantity={}&reduceOnly=true&triggerPrice={}&stopPrice={}&workingType=CONTRACT_PRICE&timestamp={}".format(
        symbol, sl_side, quantity, sl_trigger_rounded, sl_trigger_rounded, int(time.time() * 1000))
    sl_sig = get_signature(sl_params)
    sl_url = f"{BASE_URL}/fapi/v1/algoOrder?{sl_params}&signature={sl_sig}"
    sl_r = requests.post(sl_url, headers=headers, timeout=10)
    if sl_r.status_code != 200:
        if 'Invalid symbol status' in sl_r.text:
            print(f"  ⚠️ SL order failed: Symbol {symbol} cannot be traded (Invalid status)")
        else:
            print(f"  ⚠️ SL order failed: {sl_r.text[:100]}")

    if trail_exit:
        print(f"  ℹ️ TP на бирже не выставлен (SCANNER_USE_TRAIL_EXIT) — выход: position-trailer")
    elif tp_price:
        tp_trigger_rounded = round_to_tick(tp_price, tick_size)
        tp_side = "SELL" if side == "BUY" else "BUY"
        tp_params = "symbol={}&side={}&type=TAKE_PROFIT_MARKET&orderType=TAKE_PROFIT_MARKET&algoType=CONDITIONAL&quantity={}&reduceOnly=true&triggerPrice={}&stopPrice={}&workingType=CONTRACT_PRICE&timestamp={}".format(
            symbol, tp_side, quantity, tp_trigger_rounded, tp_trigger_rounded, int(time.time() * 1000))
        tp_sig = get_signature(tp_params)
        tp_url = f"{BASE_URL}/fapi/v1/algoOrder?{tp_params}&signature={tp_sig}"
        tp_r = requests.post(tp_url, headers=headers, timeout=10)
        if tp_r.status_code != 200:
            print(f"  ⚠️ TP order failed: {tp_r.text[:100]}")

    return result

def get_algo_orders_sapi():
    """Query algo orders using SAPI endpoint (works when fapi fails)"""
    try:
        ts = int(time.time() * 1000)
        params = f"timestamp={ts}"
        sig = get_signature(params)
        url = f"{BASE_URL_SPOT}/sapi/v1/algo/futures/openOrders?{params}&signature={sig}"
        r = requests.get(url, headers={'X-MBX-APIKEY': API_KEY}, timeout=10)
        if r.status_code == 200:
            return r.json().get('orders', [])
    except:
        pass
    return []

def check_margin_risk():
    """Check margin and position risk - don't overtrade"""
    ts = int(time.time() * 1000)
    sig = get_signature(f'timestamp={ts}')
    # Use v2/positionRisk for accurate entry prices
    r = requests.get(f'{BASE_URL}/fapi/v2/positionRisk?timestamp={ts}&signature={sig}',
                     headers={'X-MBX-APIKEY': API_KEY}, timeout=15)
    v2_data = r.json()
    if isinstance(v2_data, dict) and v2_data.get('code'):
        v2_positions = []
    else:
        v2_positions = v2_data

    balance = float(get_balance())
    positions = get_positions()
    
    # Build entry price map from v2
    entry_map = {p['symbol']: float(p.get('entryPrice', 0)) for p in v2_positions}
    
    notional = 0
    for p in positions:
        amt = float(p.get('positionAmt', 0))
        entry = entry_map.get(p['symbol'], 0)
        if entry == 0:
            entry = float(p.get('entryPrice', 0)) or 0
        notional += abs(amt * entry)
    
    margin_used = notional / LEVERAGE if LEVERAGE > 0 else notional
    margin_pct = (margin_used / balance * 100) if balance > 0 else 0

    only_max = getattr(config, "SCANNER_RISK_ONLY_MAX_POSITIONS", True)
    if only_max:
        safe = len(positions) < MAX_POSITIONS
    else:
        safe = margin_pct < MAX_MARGIN_PERCENT and len(positions) < MAX_POSITIONS

    return {
        'balance': balance,
        'positions': len(positions),
        'notional': notional,
        'margin_used': margin_used,
        'margin_pct': margin_pct,
        'safe_to_trade': safe,
    }

def should_add_trailing_tp(entry, current, tp, side, trailing_percent=1.5):
    """Check if trailing TP should be activated
    Activates when price moves 1.5% in profit direction
    """
    if side == "LONG":
        profit_pct = ((current - entry) / entry) * 100
        if profit_pct >= trailing_percent:
            # Move TP up by 0.5%
            new_tp = current * 1.005
            return new_tp if new_tp > tp else tp
    else:  # SHORT
        profit_pct = ((entry - current) / entry) * 100
        if profit_pct >= trailing_percent:
            new_tp = current * 0.995
            return new_tp if new_tp < tp else tp
    return None

def place_order(symbol, side, quantity):
    ts = int(time.time() * 1000)
    params = "symbol={}&side={}&type=MARKET&quantity={}&timestamp={}".format(symbol, side, quantity, ts)
    sig = get_signature(params)
    url = f"{BASE_URL}/fapi/v1/order?{params}&signature={sig}"
    headers = {'X-MBX-APIKEY': API_KEY}
    r = requests.post(url, headers=headers, timeout=15)
    return r.json()

def set_leverage(symbol, lev=LEVERAGE):
    ts = int(time.time() * 1000)
    params = "symbol={}&leverage={}&timestamp={}".format(symbol, lev, ts)
    sig = get_signature(params)
    url = f"{BASE_URL}/fapi/v1/leverage?{params}&signature={sig}"
    headers = {'X-MBX-APIKEY': API_KEY}
    r = requests.post(url, headers=headers, timeout=15)
    return r.json()

def notify_trade(notification_type, data):
    """Send notification based on config settings"""
    # Check if posting is enabled
    post_enabled = True
    try:
        post_enabled = POST_SIGNALS_TO_TELEGRAM
    except:
        pass
    
    if not post_enabled:
        return False
    
    # Check specific notification types
    if notification_type == 'open' and not data.get('NOTIFY_ON_OPEN', True):
        try:
            if not NOTIFY_ON_OPEN:
                return False
        except:
            pass
    elif notification_type == 'close' and not data.get('NOTIFY_ON_CLOSE', True):
        try:
            if not NOTIFY_ON_CLOSE:
                return False
        except:
            pass
    
    msg = ""
    
    if notification_type == 'open':
        msg = f"""🚨 *NEW POSITION OPENED*

🔖 Symbol: {data['symbol']}
📊 Direction: {data['direction']}
💵 Entry: ${data['entry']:.6f}
🛡 SL: ${data['sl']:.6f}
📈 TP: ${data['tp']:.6f}
💰 Size: {data['size']}
📋 Order ID: {data.get('order_id', 'N/A')}"""
    
    elif notification_type == 'close':
        msg = f"""🔴 *POSITION CLOSED*

🔖 Symbol: {data['symbol']}
📊 Type: {data['close_type']}  # SL or TP
💵 Entry: ${data['entry']:.6f}
💵 Exit: ${data['exit']:.6f}
💰 PnL: ${data['pnl']:.2f}
📋 Order ID: {data.get('order_id', 'N/A')}"""
    
    elif notification_type == 'breakeven':
        msg = f"""🛡 *STOP LOSS MOVED TO BREAKEVEN*

🔖 Symbol: {data['symbol']}
💵 Entry: ${data['entry']:.6f}
🛡 New SL: ${data['sl']:.6f}
💰 Current Profit: {data['profit_pct']:.2f}%"""
    
    elif notification_type == 'trailing_tp':
        msg = f"""📈 *TRAILING TP ACTIVATED*

🔖 Symbol: {data['symbol']}
📈 Old TP: ${data['old_tp']:.6f}
📈 New TP: ${data['new_tp']:.6f}
💰 Current Profit: {data['profit_pct']:.2f}%"""
    
    elif notification_type == 'error':
        msg = f"""❌ *TRADING ERROR*

🔖 Symbol: {data['symbol']}
📝 Error: {data['error']}"""
    
    if msg:
        return send_telegram(msg)
    return False

def send_telegram(msg):
    """Отправка в Telegram; при ошибке Markdown — повтор plain text (см. telegram_util)."""
    try:
        from telegram_util import send_telegram_message

        return send_telegram_message(msg)
    except ImportError:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL:
            print('[telegram] Пропуск: нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL')
            return False
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
        r = requests.post(
            url,
            data={'chat_id': TELEGRAM_CHANNEL, 'text': msg, 'parse_mode': 'Markdown'},
            timeout=15,
        )
        return r.status_code == 200

# === ANALYSIS ===
def calc_ema(prices, period):
    if len(prices) < period:
        return None
    mul = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = (p - ema) * mul + ema
    return ema

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, min(period + 1, len(candles))):
        high = float(candles[-i][1])
        low = float(candles[-i][2])
        prev = float(candles[-i-1][3])
        tr = max(high - low, abs(high - prev), abs(low - prev))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else None


def calc_bollinger_squeeze(prices, period=20):
    """Bollinger Bands Squeeze - returns squeeze score (0-2)
    Lower = more compressed (potential breakout coming)"""
    if len(prices) < period:
        return 0
    
    # Simple BB calculation
    import statistics
    recent = prices[-period:]
    sma = statistics.mean(recent)
    std = statistics.stdev(recent)
    
    # BB width
    bb_width = (max(recent) - min(recent)) / sma if sma > 0 else 0
    
    # ATR for comparison
    atr = calc_atr([[p,p,p,p,p] for p in prices[-15:]], 14) or (sma * 0.02)
    atr_width = (atr * 4) / sma if sma > 0 else 0
    
    # Squeeze = BB narrower than ATR
    if bb_width < atr_width * 0.7:
        return 2  # Strong squeeze
    elif bb_width < atr_width * 0.9:
        return 1  # Mild squeeze
    return 0  # No squeeze


def calc_rsi(prices, period=14):
    """Calculate RSI"""
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def detect_divergence(prices, period=14):
    """Detect RSI/MACD divergence.
    
    Returns:
        'BULLISH_DIV': Price lower low + indicator higher low
        'BEARISH_DIV': Price higher high + indicator lower high  
        'HIDDEN_BULLISH': Trend continuation in uptrend
        'HIDDEN_BEARISH': Trend continuation in downtrend
        'NONE': No divergence
    """
    if len(prices) < period * 2:
        return 'NONE'
    
    # Get RSI values
    rsi_values = []
    for i in range(period, len(prices)):
        deltas = [prices[j] - prices[j-1] for j in range(i-period+1, i+1)]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi_values.append(100 - (100 / (1 + rs)))
    
    if len(rsi_values) < 10:
        return 'NONE'
    
    # Compare recent price action vs indicator
    price_recent = prices[-period:]
    price_prev = prices[-period*2:-period]
    
    price_recent_low = min(price_recent)
    price_prev_low = min(price_prev)
    price_recent_high = max(price_recent)
    price_prev_high = max(price_prev)
    
    rsi_recent_low = min(rsi_values[-period:])
    rsi_prev_low = min(rsi_values[-period*2:-period])
    rsi_recent_high = max(rsi_values[-period:])
    rsi_prev_high = max(rsi_values[-period:])
    
    # Bullish divergence: price making lower low, RSI higher low
    if price_recent_low < price_prev_low and rsi_recent_low > rsi_prev_low:
        return 'BULLISH_DIV'
    
    # Bearish divergence: price making higher high, RSI lower high
    if price_recent_high > price_prev_high and rsi_recent_high < rsi_prev_high:
        return 'BEARISH_DIV'
    
    # Hidden bullish: price higher low, RSI lower low (continuation)
    if price_recent_low > price_prev_low and rsi_recent_low < rsi_prev_low:
        return 'HIDDEN_BULLISH'
    
    # Hidden bearish: price lower high, RSI higher high (continuation)
    if price_recent_high < price_prev_high and rsi_recent_high > rsi_prev_high:
        return 'HIDDEN_BEARISH'
    
    return 'NONE'


def calc_confidence(analysis, direction):
    """Calculate confidence score (0-1) based on multiple factors."""
    score = 0.5  # Base
    
    # RSI in good zone (not overbought/oversold) = +0.1
    rsi = analysis.get('rsi_14', 50)
    if direction == 'LONG' and 30 < rsi < 60:
        score += 0.1
    elif direction == 'SHORT' and 40 < rsi < 70:
        score += 0.1
    
    # MACD histogram aligned = +0.15
    macd_h = analysis.get('macd_histogram', 0)
    if direction == 'LONG' and macd_h > 0:
        score += 0.15
    elif direction == 'SHORT' and macd_h < 0:
        score += 0.15
    
    # Volume confirmation = +0.1
    if analysis.get('vol_ratio', 1) > 2:
        score += 0.1
    
    # Bollinger squeeze (potential breakout) = +0.1
    if analysis.get('squeeze', 0) > 0:
        score += 0.1
    
    # EMA position aligned = +0.1
    ema_pos = analysis.get('ema_position', 50)
    if direction == 'LONG' and ema_pos < 50:
        score += 0.1
    elif direction == 'SHORT' and ema_pos > 50:
        score += 0.1
    
    # Strong weekly change = +0.1
    weekly = abs(analysis.get('weekly_change', 0))
    if weekly > 10:
        score += 0.1
    
    return min(1.0, max(0.0, score))


def get_signal_tier(score, direction):
    """Convert confidence score to 7-tier signal.
    
    For LONG/BUY signals:
    - STRONG_BUY: score >= 0.8
    - BUY: score >= 0.65
    - WEAK_BUY: score >= 0.5
    - NEUTRAL: score >= 0.4
    - WEAK_SELL: score >= 0.3
    - SELL: score >= 0.15
    - STRONG_SELL: score < 0.15
    
    For SHORT/SELL signals (inverted):
    - STRONG_SELL: score <= 0.2
    - SELL: score <= 0.35
    - WEAK_SELL: score <= 0.5
    - NEUTRAL: score > 0.5
    """
    if direction == 'LONG':
        if score >= 0.8:
            return 'STRONG_BUY'
        elif score >= 0.65:
            return 'BUY'
        elif score >= 0.5:
            return 'WEAK_BUY'
        elif score >= 0.4:
            return 'NEUTRAL'
        elif score >= 0.3:
            return 'WEAK_SELL'
        elif score >= 0.15:
            return 'SELL'
        else:
            return 'STRONG_SELL'
    else:  # SHORT
        if score <= 0.2:
            return 'STRONG_SELL'
        elif score <= 0.35:
            return 'SELL'
        elif score <= 0.5:
            return 'WEAK_SELL'
        elif score <= 0.65:
            return 'NEUTRAL'
        elif score <= 0.8:
            return 'WEAK_BUY'
        else:
            return 'STRONG_BUY'





def calc_williams_r(high, low, close, period=14):
    """Calculate Williams %R - best oscillating indicator per backtests"""
    if len(high) < period:
        return -50  # Neutral
    
    highest_high = max(high[-period:])
    lowest_low = min(low[-period:])
    
    if highest_high == lowest_low:
        return -50
    
    wr = ((highest_high - close) / (highest_high - lowest_low)) * -100
    return wr


def calc_macd(prices, fast=12, slow=26, signal=9):
    """Calculate MACD histogram. Returns (macd, signal_line, histogram)"""
    if len(prices) < slow:
        return None, None, None
    
    # Calculate EMAs
    def ema(prices, period):
        k = 2 / (period + 1)
        ema_val = prices[0]
        for price in prices[1:]:
            ema_val = price * k + ema_val * (1 - k)
        return ema_val
    
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_line = ema_fast - ema_slow
    
    # Signal line (EMA of MACD)
    macd_values = [macd_line]  # simplified - use current macd
    signal_line = ema(macd_values, signal)
    
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def _analyze_symbol_minimal(symbol: str, stats: dict, candles: list, price_change: float):
    """
    Упрощённый сигнал: только |24h change| ≥ MIN_PRICE_CHANGE и SL/TP по ATR/price fallback.
    Без отсечек по скору, MACD, EMA-«перекупленности» — единственный внешний лимит в main(): MAX_POSITIONS.
    """
    closes = [float(c[4]) for c in candles]
    opens = [float(c[1]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    volumes = [float(c[5]) for c in candles]
    current = closes[-1]
    if abs(price_change) < MIN_PRICE_CHANGE:
        return None

    avg_vol = sum(volumes[-24:]) / 24 if len(volumes) >= 24 else sum(volumes) / len(volumes)
    recent_vol = volumes[-1]
    vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0

    change_1h = ((closes[-1] - closes[-6]) / closes[-6]) * 100 if len(closes) >= 6 else 0.0
    recent_high = max(highs[-10:])
    prev_high = max(highs[-20:-10]) if len(highs) >= 20 else max(highs[:-10])
    recent_low = min(lows[-10:])
    prev_low = min(lows[-20:-10]) if len(lows) >= 20 else min(lows[:-10])
    breakout = recent_high > prev_high * 1.02
    breakdown = recent_low < prev_low * 0.98

    direction = "LONG" if price_change > 0 else "SHORT"
    atr = calc_atr(candles, 14) or (current * 0.02)
    atr_pct = (atr / current * 100) if current > 0 else 0

    ema_21 = calc_ema(closes, 21) or current
    ema_50 = calc_ema(closes, 50) or current
    ema_21_val = ema_21
    atr_current = atr
    ema_position = (
        ((current - (ema_21_val - atr_current)) / (atr_current * 2)) * 100 if atr_current > 0 else 50.0
    )

    if atr_pct >= PRICE_FALLBACK_MIN_ATR and atr_pct <= PRICE_FALLBACK_MAX_ATR:
        if atr_pct > ATR_HIGH_VOLATILITY:
            atr_mult_sl = ATR_MULTIPLIER_SL_HIGH
            atr_mult_tp = ATR_MULTIPLIER_TP_HIGH
        else:
            atr_mult_sl = ATR_MULTIPLIER_SL_NORMAL
            atr_mult_tp = ATR_MULTIPLIER_TP_NORMAL
        if direction == "LONG":
            sl = current - (atr * atr_mult_sl)
            tp1 = current + (atr * atr_mult_tp)
        else:
            sl = current + (atr * atr_mult_sl)
            tp1 = current - (atr * atr_mult_tp)
        tp2 = None
        sl_method = "ATR"
    else:
        _cap = config.max_sl_price_move_pct()
        if direction == "LONG":
            sl = current * (1 - _cap / 100)
            tp1 = current * (1 + PRICE_TP / 100)
        else:
            sl = current * (1 + _cap / 100)
            tp1 = current * (1 - PRICE_TP / 100)
        tp2 = None
        sl_method = "PRICE"
    sl = config.clamp_sl_price_to_leverage(direction, current, sl)

    trend = "BULLISH" if current > ema_50 else "BEARISH"
    if breakout and direction == "LONG":
        structure = "BREAKOUT"
    elif breakdown and direction == "SHORT":
        structure = "BREAKDOWN"
    elif price_change > 10:
        structure = "STRONG_MOMENTUM"
    elif price_change < -10:
        structure = "STRONG_DOWNSIDE"
    else:
        structure = "MOMENTUM"

    resistance = max(highs[-50:]) if len(highs) >= 50 else max(highs)
    support = min(lows[-50:]) if len(lows) >= 50 else min(lows)

    rsi = 50.0
    try:
        gains = losses = 0.0
        for i in range(1, 15):
            if i >= len(closes):
                break
            diff = closes[-i] - closes[-i - 1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        avg_gain = gains / 14 if gains else 0
        avg_loss = losses / 14 if losses else 0
        rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss > 0 else 50.0
    except Exception:
        pass

    oi_data = get_oi_history(symbol)
    oi = oi_data.get("current", 0)
    oi_change = oi_data.get("change_pct", 0)
    oi_trend = oi_data.get("trend", "neutral")

    r_weekly = requests.get(
        f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval=1w&limit=5", timeout=10
    )
    weekly_candles = r_weekly.json()
    weekly_change = 0.0
    if len(weekly_candles) >= 2:
        wo = float(weekly_candles[-1][1])
        wc = float(weekly_candles[-1][4])
        weekly_change = ((wc - wo) / wo) * 100 if wo else 0.0

    sma_50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else closes[-1]
    is_green = closes[-1] > opens[-1] if opens else True
    past_10_vol_max = max(volumes[-10:])
    pocket_pivot = (current > sma_50) and is_green and (recent_vol > past_10_vol_max)

    macd_line, signal_line, histogram = calc_macd(closes)
    squeeze = calc_bollinger_squeeze(closes)

    coin_category = "SAFE" if symbol in SAFE_COINS else "OTHER"

    return {
        "symbol": symbol,
        "direction": direction,
        "current": current,
        "price_change": price_change,
        "change_1h": change_1h,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "atr": atr,
        "atr_pct": atr_pct,
        "sl_method": sl_method,
        "rsi": rsi,
        "ema_21": ema_21,
        "ema_50": ema_50,
        "trend": trend,
        "structure": structure,
        "support": support,
        "resistance": resistance,
        "vol_spike": vol_ratio > 2,
        "vol_ratio": vol_ratio,
        "breakout": breakout,
        "runner_score": 1,
        "oi": oi,
        "oi_change": oi_change,
        "oi_trend": oi_trend,
        "category": coin_category,
        "weekly_change": weekly_change,
        "pocket_pivot": pocket_pivot,
        "dcr": 0.0,
        "vcs": False,
        "vcs_score": 50.0,
        "trend_base": True,
        "pp_count": 0,
        "ema_position": ema_position,
        "divergence": "NONE",
        "confidence": 0.5,
        "signal_tier": "NEUTRAL",
        "macd_histogram": histogram if histogram is not None else 0,
        "squeeze": squeeze,
        "final_score": 1.0,
        "adx_data": None,
        "btc_correlation": None,
        "session_data": None,
        "score_adjustments": ["minimal_analysis"],
    }


def analyze_symbol(symbol, stats):
    """Runner-focused analysis - look for momentum explosions"""
    stat = stats.get(symbol, {})
    price_change = float(stat.get('priceChangePercent', 0))
    
    # Get candles first to check volume/momentum
    candles = get_klines(symbol, '1h', 50)
    if not candles or len(candles) < 20:
        return None

    if getattr(config, "SCANNER_MINIMAL_ANALYSIS", True):
        return _analyze_symbol_minimal(symbol, stats, candles, price_change)
    
    closes = [float(c[4]) for c in candles]  # index 4 = close
    opens = [float(c[1]) for c in candles]     # index 1 = open
    highs = [float(c[2]) for c in candles]    # index 2 = high
    lows = [float(c[3]) for c in candles]     # index 3 = low
    volumes = [float(c[5]) for c in candles] # index 5 = volume
    current = closes[-1]
    
    # === RUNNER CRITERIA ===
    # 1. Volume Spike (5x+ average)
    avg_vol = sum(volumes[-24:]) / 24 if len(volumes) >= 24 else sum(volumes) / len(volumes)
    recent_vol = volumes[-1]
    vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1
    
    # Get weekly data
    r_weekly = requests.get(f'{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval=1w&limit=5', timeout=10)
    weekly_candles = r_weekly.json()
    weekly_change = 0
    if len(weekly_candles) >= 2:
        weekly_open = float(weekly_candles[-1][1])
        weekly_close = float(weekly_candles[-1][4])
        weekly_change = ((weekly_close - weekly_open) / weekly_open) * 100
    
    # 2. 1H Momentum (continuation)
    change_1h = ((closes[-1] - closes[-6]) / closes[-6]) * 100 if len(closes) >= 6 else 0
    
    # 3. Breakout/Breakdown (breaking recent high/low)
    recent_high = max(highs[-10:])
    prev_high = max(highs[-20:-10]) if len(highs) >= 20 else max(highs[:-10])
    recent_low = min(lows[-10:])
    prev_low = min(lows[-20:-10]) if len(lows) >= 20 else min(lows[:-10])
    breakout = recent_high > prev_high * 1.02  # 2% above for LONG
    breakdown = recent_low < prev_low * 0.98  # 2% below for SHORT
    
    # 4. Pocket Pivot Detection (price > 50SMA, green candle, vol spike)
    sma_50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else closes[-1]
    is_green_candle = closes[-1] > opens[-1] if len(opens) > 0 else True
    past_10_vol_max = max(volumes[-10:])
    pocket_pivot = (current > sma_50) and is_green_candle and (recent_vol > past_10_vol_max)
    
    # 5. DCR% (Daily Closing Range %)
    dcr = ((current - lows[-1]) / (highs[-1] - lows[-1])) * 100 if (highs[-1] - lows[-1]) > 0 else 0
    
    # 6. VCS - Volatility Contraction Score (based on ATR compression)
    # Low ATR relative to recent = contraction
    atr_current = calc_atr(candles, 14) or (current * 0.02)
    atr_avg = sum(calc_atr(candles[i:i+5], 14) or (closes[i] * 0.02) for i in range(min(10, len(candles)-5))) / min(10, len(candles)-5) if len(candles) > 5 else atr_current
    vcs_score = 100 - (atr_current / atr_avg * 100) if atr_avg > 0 else 50  # Higher = more contracted
    vcs = vcs_score > 30  # Contraction detected
    
    # 7. Trend Base (price > 50SMA AND 10WMA > 30WMA)
    wma_10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else closes[-1]
    wma_30 = sum(closes[-30:]) / 30 if len(closes) >= 30 else closes[-1]
    trend_base = (current > sma_50) and (wma_10 > wma_30)
    
    # 8. PP Count - count pocket pivots in last 30 days
    pp_count = 0
    for i in range(20, len(closes)-1):
        if i >= 50:  # Need 50 EMA
            vol_high = max(volumes[i-10:i])
            if volumes[i] > vol_high and closes[i] > sum(closes[i-50:i-40])/10:
                pp_count += 1
    
    # 9. 21EMA position in ATR range
    ema_21_val = calc_ema(closes, 21) or current
    ema_position = ((current - (ema_21_val - atr_current)) / (atr_current * 2)) * 100 if atr_current > 0 else 50
    
    # Open Interest - use enhanced OI history
    oi_data = get_oi_history(symbol)
    oi = oi_data.get('current', 0)
    oi_change = oi_data.get('change_pct', 0)
    oi_trend = oi_data.get('trend', 'neutral')
    
    # === NEW INDICATORS v1.0.29 ===
    
    # 10. RSI (14) - Oversold/Oversold
    def calc_rsi(closes, period=14):
        if len(closes) < period + 1:
            return 50
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    rsi_14 = calc_rsi(closes, 14)
    # RSI-based filter: reject bad entries
    squeeze = 0  # Initialize early to avoid "not defined" errors
    rsi_oversold = rsi_14 < 30
    rsi_overbought = rsi_14 > 70
    rsi_signal = rsi_oversold or rsi_overbought
    
    # 11. MACD Histogram Cross
    ema_12 = calc_ema(closes[-26:], 12) if len(closes) >= 26 else calc_ema(closes, 12)
    ema_26 = calc_ema(closes[-26:], 26) if len(closes) >= 26 else calc_ema(closes, 26)
    
    macd_line = ema_12 - ema_26 if ema_12 and ema_26 else 0
    
    # Signal line = EMA of MACD
    macd_hist_current = 0
    macd_hist_prev = 0
    if len(closes) >= 35:
        # Calculate MACD for previous candle
        ema_12_prev = calc_ema(closes[-27:-1], 12)
        ema_26_prev = calc_ema(closes[-27:-1], 26)
        macd_prev = ema_12_prev - ema_26_prev if ema_12_prev and ema_26_prev else 0
        # Signal prev = EMA of MACD prev
        signal_prev = calc_ema([macd_prev] * 9, 9) if macd_prev else 0
        macd_hist_prev = macd_prev - signal_prev if signal_prev else 0
        # Signal current
        signal_current = calc_ema([macd_prev, macd_line], 9) if macd_prev else macd_line
        macd_hist_current = macd_line - signal_current if signal_current else 0
    
    macd_cross = (macd_hist_current > 0 and macd_hist_prev < 0) or (macd_hist_current < 0 and macd_hist_prev > 0)
    
    # 12. Bollinger Bands Touch
    sma_20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else sum(closes) / len(closes)
    std_20 = (sum((c - sma_20) ** 2 for c in closes[-20:]) / 20) ** 0.5 if len(closes) >= 20 else sma_20 * 0.02
    bb_upper = sma_20 + (2 * std_20)
    bb_lower = sma_20 - (2 * std_20)
    bb_touch = (current >= bb_upper * 0.99) or (current <= bb_lower * 1.01)  # Near bands
    
    # 13. VWAP Cross (price crossing VWAP)
    if len(candles) >= 24:
        typical_prices = [(float(c[2]) + float(c[3]) + float(c[4])) / 3 for c in candles[-24:]]
        volumes_24 = [float(c[5]) for c in candles[-24:]]
        vwap = sum(tp * v for tp, v in zip(typical_prices, volumes_24)) / sum(volumes_24) if sum(volumes_24) > 0 else current
    else:
        vwap = current
    vwap_cross = (closes[-1] > vwap > closes[-2]) or (closes[-1] < vwap < closes[-2])
    
    # 14. Extra Volume Score (5x+ avg - extra bonus)
    extra_vol_score = 1 if vol_ratio > 5 else 0  # Reduced
    
    # Runner score - updated with new setups
    runner_score = 0
    
    # Volume - REDUCED (was too aggressive, caused false signals)
    if vol_ratio > 5: runner_score += 1  # 5x+ only
    elif vol_ratio > 3: runner_score += 1
    
    # Price changes
    if price_change > 10: runner_score += 2
    elif price_change > 5: runner_score += 1
    if abs(change_1h) > 3: runner_score += 1
    
    # Breakout/Breakdown - REMOVED (poor accuracy)
    pass
    
    # OI
    if oi_change > 20: runner_score += 2
    elif oi_change > 10: runner_score += 1
    
    # New setups scoring
    if weekly_change > 20: runner_score += 2  # Weekly 20%+ (max +2, reduced from +3)
    elif weekly_change > 10: runner_score += 1
    elif weekly_change > 3: runner_score += 1
    
    # Pocket Pivot - REMOVED (poor accuracy)
    pass
    if trend_base: runner_score += 1
    if 0 <= ema_position <= 100 and ema_position < 50: runner_score += 1  # Price near 21EMA
    
    # NEW INDICATORS v1.0.29
    if rsi_signal: runner_score += 1  # RSI <30 or >70
    if extra_vol_score > 0: runner_score += extra_vol_score  # Volume 5x+ (extra +2)
    
    # ── STRATEGY IMPROVEMENTS v2.0 ────────────────────────────────────────
    final_score = runner_score
    score_adjustments: list = []
    adx_data = None
    btc_corr = None
    session_data = None
    try:
        improved = si.calculate_improved_score(runner_score, symbol, {
            'direction': 'LONG' if price_change > 0 else 'SHORT',
            'vol_ratio': vol_ratio,
            'oi_change': oi_change,
            'price_change': price_change
        }, candles)
        
        final_score = improved['final_score']
        score_adjustments = improved['adjustments']
        adx_data = improved['adx']
        btc_corr = improved['btc_correlation']
        session_data = improved['session']
        
        if score_adjustments:
            print(f"      Improvements: {', '.join(score_adjustments)}")
    except Exception as e:
        final_score = runner_score
        score_adjustments = []
        adx_data = None
        btc_corr = None
        session_data = None
    # ────────────────────────────────────────────────────────────────────────

    # Optional RL policy hook (offline model; disabled unless USE_RL_POLICY=1)
    try:
        if os.environ.get("USE_RL_POLICY", "").strip().lower() in ("1", "true", "yes", "on"):
            import rl_scanner_hook as _neko_rl
            _adj = float(_neko_rl.score_adjustment(symbol, float(final_score)))
            if _adj:
                final_score = max(0.0, final_score + _adj)
    except Exception:
        pass
    
    # Must have at least MIN_SCORE (use final improved score)
    if final_score < MIN_SCORE:
        return None
    
    # Must have significant change for signal (either direction)
    if abs(price_change) < MIN_PRICE_CHANGE:
        return None
    
    # Debug: log score breakdown for analysis
    debug_info = {
        'vol': vol_ratio,
        'chg': price_change,
        'weekly': weekly_change,
        'oi': oi_change,
        'ema': ema_position,
        'rsi': rsi_14,
        'score': final_score  # Use improved score
    }
    
    # Direction - Detect LONG or SHORT (MUST BE FIRST)
    if price_change > 0:
        direction = "LONG"
    else:
        direction = "SHORT"
    
    # EMA Filter - for LONG, price should be near or below 21EMA (not extended)
    # ema_position > 80 means price is extended above ATR bands
    if direction == "LONG" and ema_position > 85:
        # Price too extended above ATR bands, likely a chase
        return None
    if direction == "SHORT" and ema_position < 15:
        # Price too extended below ATR bands for shorts
        return None
    
    # EMAs
    ema_21 = calc_ema(closes, 21)
    ema_50 = calc_ema(closes, 50)
    if not ema_21 or not ema_50:
        return None
    
    # ATR for SL/TP
    atr = calc_atr(candles, 14) or (current * 0.02)
    atr_pct = (atr / current * 100) if current > 0 else 0
    
    # RSI Signal - just log, don't reject (research shows RSI alone is not reliable)
    rsi_signal = "OB" if rsi_14 > 70 else "OS" if rsi_14 < 30 else "Neutral"

    # MACD Histogram Filter - confirm momentum direction
    macd_line, signal_line, histogram = calc_macd(closes)
    if histogram is not None:
        if direction == "LONG" and histogram < 0:
            # MACD bearish - reject LONG
            return None
        if direction == "SHORT" and histogram > 0:
            # MACD bullish - reject SHORT
            return None
    
    # Calculate divergence for signal quality
    divergence = detect_divergence(closes)
    
    # Calculate confidence score
    temp_analysis = {
        'rsi_14': rsi_14,
        'macd_histogram': histogram if histogram is not None else 0,
        'vol_ratio': vol_ratio,
        'squeeze': 0,  # placeholder
        'ema_position': ema_position,
        'weekly_change': weekly_change,
    }
    confidence = calc_confidence(temp_analysis, direction)
    signal_tier = get_signal_tier(confidence, direction)
    

    
    # Bollinger Squeeze - just score it, don't reject
    squeeze = calc_bollinger_squeeze(closes)
    if squeeze > 0:
        runner_score += 1  # Squeeze is good for volatility breakout
    if direction == "SHORT" and rsi_oversold:
        # Don't SHORT when RSI oversold (<30) - too risky  
        return None
    
    if atr_pct >= PRICE_FALLBACK_MIN_ATR and atr_pct <= PRICE_FALLBACK_MAX_ATR:
        # ATR-based SL/TP (anti-fakeout: wider multipliers)
        if atr_pct > ATR_HIGH_VOLATILITY:
            atr_mult_sl = ATR_MULTIPLIER_SL_HIGH
            atr_mult_tp = ATR_MULTIPLIER_TP_HIGH
        else:
            atr_mult_sl = ATR_MULTIPLIER_SL_NORMAL
            atr_mult_tp = ATR_MULTIPLIER_TP_NORMAL
        
        if direction == "LONG":
            sl = current - (atr * atr_mult_sl)
            tp1 = current + (atr * atr_mult_tp)
        else:
            sl = current + (atr * atr_mult_sl)
            tp1 = current - (atr * atr_mult_tp)
        tp2 = None
        sl_method = "ATR"
    else:
        # Fallback: не использовать фикс. PRICE_SL=5% — при x50 это даёт ~−250% ROI на маржу.
        # Берём тот же потолок, что и clamp (≈ MAX_LOSS_ROI_PCT_AT_SL / L % цены, см. config).
        _cap = config.max_sl_price_move_pct()
        if direction == "LONG":
            sl = current * (1 - _cap / 100)
            tp1 = current * (1 + PRICE_TP / 100)
        else:
            sl = current * (1 + _cap / 100)
            tp1 = current * (1 - PRICE_TP / 100)
        tp2 = None
        sl_method = "PRICE"

    # Плечо x50+: не оставлять SL в 10–30% от цены — подтянуть к max_sl_price_move_pct()
    sl = config.clamp_sl_price_to_leverage(direction, current, sl)
    
    # Trend
    trend = "BULLISH" if current > ema_50 else "BEARISH"
    
    # Structure
    if breakout and direction == "LONG":
        structure = "BREAKOUT"
    elif breakout and direction == "SHORT":
        structure = "BREAKDOWN"
    elif price_change > 10:
        structure = "STRONG_MOMENTUM"
    elif price_change < -10:
        structure = "STRONG_DOWNSIDE"
    else:
        structure = "MOMENTUM"
    
    # Support/Resistance
    resistance = max(highs[-50:]) if len(highs) >= 50 else max(highs)
    support = min(lows[-50:]) if len(lows) >= 50 else min(lows)
    
    # RSI
    rsi = 50
    try:
        gains, losses = 0, 0
        for i in range(1, 15):
            if i >= len(closes): break
            diff = closes[-i] - closes[-i-1]
            if diff > 0: gains += diff
            else: losses -= diff
        avg_gain = gains / 14 if gains else 0
        avg_loss = losses / 14 if losses else 0
        rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss > 0 else 50
    except:
        rsi = 50
    
    # Get Open Interest data
    # Determine coin category
    coin_category = 'SAFE' if symbol in SAFE_COINS else 'OTHER'
    
    return {
        'symbol': symbol,
        'direction': direction,
        'current': current,
        'price_change': price_change,
        'change_1h': change_1h,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'atr': atr,
        'atr_pct': atr_pct,
        'sl_method': sl_method,
        'rsi': rsi,
        'ema_21': ema_21,
        'ema_50': ema_50,
        'trend': trend,
        'structure': structure,
        'support': support,
        'resistance': resistance,
        'vol_spike': vol_ratio > 2,
        'vol_ratio': vol_ratio,
        'breakout': breakout,
        'runner_score': runner_score,
        'oi': oi,
        'oi_change': oi_change,
        'oi_trend': oi_trend,
        'category': coin_category,  # SAFE or OTHER
        # New setups
        'weekly_change': weekly_change,
        'pocket_pivot': pocket_pivot,
        'dcr': dcr,
        'vcs': vcs,
        'vcs_score': vcs_score,
        'trend_base': trend_base,
        'pp_count': pp_count,
        'ema_position': ema_position,
        # Phase 1: Divergence, Confidence, Signal Tier
        'divergence': 'NONE',
        'confidence': 0.5,
        'signal_tier': 'NEUTRAL',
        'macd_histogram': histogram if 'histogram' in locals() else 0,
        'squeeze': squeeze if 'squeeze' in locals() else 0,
        # Strategy Improvements v2.0
        'final_score': final_score,
        'adx_data': adx_data,
        'btc_correlation': btc_corr,
        'session_data': session_data,
        'score_adjustments': score_adjustments,
    }

def fetch_brave_news(query, count=2):
    """Fetch news using Brave Search API"""
    try:
        import requests
        brave_key = os.environ.get('BRAVE_API_KEY', '')
        url = f"https://api.search.brave.com/res/v1/web/search?q={query}&count={count}"
        headers = {"Accept": "application/json", "X-Subscription-Token": brave_key}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            results = data.get('web', {}).get('results', [])
            news = []
            for item in results[:count]:
                title = item.get('title', '')[:50]
                if title:
                    news.append(title)
            return news if news else None
    except:
        pass
    return None

def get_token_news(symbol, stats):
    """Get latest info for a token - price action + market context + real news"""
    sym = symbol.replace('USDT', '')
    
    # Token name mapping for search
    token_names = {
        'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'BNB': 'Binance', 'SOL': 'Solana',
        'XRP': 'XRP Ripple', 'ADA': 'Cardano', 'DOGE': 'Dogecoin', 'AVAX': 'Avalanche',
        'DOT': 'Polkadot', 'MATIC': 'Polygon', 'LINK': 'Chainlink', 'UNI': 'Uniswap',
        'ATOM': 'Cosmos', 'LTC': 'Litecoin', 'FIL': 'Filecoin', 'AAVE': 'Aave',
        'PEPE': 'Pepe crypto', 'SHIB': 'Shiba Inu', 'WIF': 'dogwifhat', 'BONK': 'Bonk',
        'INJ': 'Injective', 'OP': 'Optimism', 'ARB': 'Arbitrum', 'TIA': 'Celestia',
        'SUI': 'Sui blockchain', 'SEI': 'Sei blockchain', 'NEAR': 'NEAR Protocol',
        'APT': 'Aptos', 'RUNE': 'THORChain', 'GRT': 'The Graph', 'ENS': 'Ethereum Name Service',
        'IMX': 'Immutable X', 'STX': 'Stacks', 'RNDR': 'Render Token',
        'XAN': 'XANA metaverse', 'AXS': 'Axie Infinity', 'FTM': 'Fantom',
        'GALA': 'Gala', 'SAND': 'The Sandbox', 'MANA': 'Decentraland',
        'ALGO': 'Algorand', 'VET': 'VeChain', 'THETA': 'Theta'
    }
    
    # Get real news first
    token_name = token_names.get(sym, sym)
    real_news = None
    try:
        import requests
        # Use web search for news
        brave_url = "https://api.search.brave.com/res/v1/web/search"
        headers = {"Accept": "application/json"}
        params = {"q": f"{token_name} crypto news 2026", "count": 2}
        r = requests.get(brave_url, params=params, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            results = data.get('web', {}).get('results', [])
            if results:
                news_titles = [r.get('title', '')[:45] for r in results[:2] if r.get('title')]
                if news_titles:
                    real_news = " | ".join(news_titles)
    except:
        pass
    
    # Get stats
    stat = stats.get(symbol, {})
    change_24h = float(stat.get('priceChangePercent', 0))
    volume = float(stat.get('volume', 0))
    high_24h = float(stat.get('highPrice', 0))
    low_24h = float(stat.get('lowPrice', 0))
    
    # Format volume
    if volume > 1e9:
        vol_str = f"${volume/1e9:.1f}B"
    elif volume > 1e6:
        vol_str = f"${volume/1e6:.1f}M"
    else:
        vol_str = f"${volume/1e3:.1f}K"
    
    # Market context
    if change_24h > 10:
        context = "🔥 Hot momentum"
    elif change_24h > 5:
        context = "📈 Strong gain"
    elif change_24h > 0:
        context = "📊 Positive"
    elif change_24h < -10:
        context = "💥 Heavy selloff"
    elif change_24h < -5:
        context = "📉 Sharp drop"
    else:
        context = "➡️ Sideways"
    
    # If we have real news, use it
    if real_news:
        return f"📰 {real_news}"
    
    return f"{context} | 24h: {change_24h:+.2f}% | Vol: {vol_str}"

def _scanner_effective_direction(direction: str) -> str:
    if config.invert_signals_enabled():
        return "SHORT" if direction == "LONG" else "LONG"
    return direction


def _telegram_trail_exit_blurb() -> str:
    if not getattr(config, "SCANNER_USE_TRAIL_EXIT", True):
        return ""
    try:
        cap = float(config.MAX_LOSS_ROI_PCT_AT_SL)
    except Exception:
        cap = 20.0
    try:
        ref_lev = float(getattr(config, "TRAIL_LADDER_REF_LEVERAGE", 50.0))
    except Exception:
        ref_lev = 50.0
    if abs(ref_lev - round(ref_lev)) < 1e-9:
        ref_txt = f"{int(round(ref_lev))}"
    else:
        ref_txt = f"{ref_lev:g}"
    return (
        "🔄 Trailing SL (position-trailer, HWM): пороги заданы для эталона x"
        f"{ref_txt}; в %% на маржу они ×(ваше плечо/x{ref_txt}) — при меньшем плече шаги уже. "
        f"Старт ≈ −{cap:.0f}% ROI → при HWM 20–40% плавно BE→20% на маржу (трейл) → шаги 20% до 200% → ступени по 50% до 500% → выше по 100%. "
        "Лимитный TP не ставится.\n"
        f"🛡 Стартовый риск на бирже: до около −{cap:.0f}% ROI на маржу (см. MAX_LOSS_ROI_PCT_AT_SL)."
    )


def _telegram_sl_tp_lines(s: dict) -> str:
    trail = getattr(config, "SCANNER_USE_TRAIL_EXIT", True)
    ref = ""
    if trail and getattr(config, "SCANNER_TELEGRAM_SHOW_ATR_REFERENCE", True):
        ref = f"📐 ATR-ориентир (не ордер на бирже): ${s['tp1']:.6f}\n"
    if trail:
        return (
            f"🛡 Стартовый SL: ${s['sl']:.6f} ({s.get('sl_method', 'ATR')})\n"
            f"{ref}"
            f"{_telegram_trail_exit_blurb()}\n"
        )
    return (
        f"🛡 SL: ${s['sl']:.6f} ({s.get('sl_method', 'ATR')}-based)\n"
        f"📈 TP: ${s['tp1']:.6f}\n"
    )


def format_signal(analysis, stats):
    s = analysis
    sym = s['symbol'].replace('USDT', '')
    emoji = "🟢" if s['direction'] == "LONG" else "🔴"
    inv = ""
    if config.invert_signals_enabled():
        eff = _scanner_effective_direction(s["direction"])
        inv = f"⚠️ Фактическое открытие: {eff} (инверсия от сигнала {s['direction']}).\n\n"
    
    # Get token context
    news = get_token_news(s['symbol'], stats)
    
    # Format OI
    oi = s.get('oi', 0)
    oi_change = s.get('oi_change', 0)
    oi_trend = s.get('oi_trend', 'neutral')
    oi_str = f"{oi:,.0f}" if oi else "N/A"
    oi_emoji = "📈" if oi_change > 10 else "📉" if oi_change < -10 else "➡️"
    trend_emoji = "⬆️" if oi_trend == 'up' else "⬇️" if oi_trend == 'down' else "➡️"
    
    msg = f"""{emoji} {s['direction']} SIGNAL {emoji}

{inv}📈 {sym}USDT TECHNICAL ANALYSIS 📊
📊 Chart: https://www.tradingview.com/chart/?symbol=BINANCE:{sym}USDT

📐 MULTI-TF CONFIRMATION:
• Trend 1H: {s['trend']}
• Structure: {s['structure']}
📊 24h Change: {s['price_change']:.2f}%

📐 INDICATORS:
• RSI (14): {s['rsi']:.1f}
• EMA 21: {s['ema_21']:.6f}
• EMA 50: {s['ema_50']:.6f}
• ATR: {s['atr']:.6f}

📊 OPEN INTEREST:
• OI: {oi_str}
• OI Change: {oi_emoji} {oi_change:+.1f}%
• OI Trend: {trend_emoji} {oi_trend.upper()}

🔊 VOLUME: {'Volume Spike' if s['vol_spike'] else 'Normal'}

📊 MOMENTUM SETUPS (v1.0.30):
• Weekly: {s.get('weekly_change', 0):+.1f}%
• Pocket Pivot: {'✅ Yes' if s.get('pocket_pivot') else '❌ No'}
• OI Change: {s.get('oi_change', 0):+.1f}%
• Volume Spike: {s.get('vol_ratio', 0):.1f}x

🎯 KEY INDICATORS:
• RSI Signal: {'🔥 OB' if s.get('rsi', 50) > 70 else '❄️ OS' if s.get('rsi', 50) < 30 else '➡️ Neutral'}
• Volume 5x+: {'🔥 Yes' if s.get('vol_ratio', 0) > 5 else '❌ No'}
• Breakout: {'✅ Yes' if s.get('breakout') else '❌ No'}
• Filter: {'✅ PASSED' if filter_signal(s.get('symbol',''), s)[0] else '❌ REJECTED'}
• Score: {s.get('runner_score', 0)}/10

🆕 PHASE 1 INDICATORS:
• Divergence: {s.get('divergence', 'NONE')}
• Confidence: {s.get('confidence', 0.5):.0%}
• Signal: {s.get('signal_tier', 'NEUTRAL')}

⏱️ COOLDOWN: 2h after SL
• Support: {s['support']:.6f}
• Resistance: {s['resistance']:.6f}

🎯 RUNNER METRICS:
• 1H Momentum: {s.get('change_1h', 0):+.1f}%
• Volume Spike: {s.get('vol_ratio', 1):.1f}x
• Breakout: {'✅ Yes' if s.get('breakout') else '❌ No'}
• Score: {s.get('runner_score', 0)}/10 🚀

💡 INSIGHT: {s['direction']} | {s['structure']} | RSI: {s['rsi']:.1f}
🎯 Entry: ${s['current']:.6f}
{_telegram_sl_tp_lines(s)}📊 ATR%: {s.get('atr_pct', 0):.2f}% | Volatility: {'HIGH' if s.get('atr_pct',0)>3 else 'NORMAL' if s.get('atr_pct',0)>1 else 'LOW'}
⏰ Timeframe: 1H

📰 {news}
"""
    return msg


def _signal_indicators_from_analysis(analysis: dict) -> dict:
    """Поля для SQLite signals (совместимо с signals_db snapshots)."""
    return {
        "volume_ratio": float(analysis.get("vol_ratio", 1) or 1),
        "price_change_pct": float(analysis.get("price_change", 0) or 0),
        "price_vs_ema": float(analysis.get("ema_position", 0) or 0),
        "rsi": float(analysis.get("rsi", 50) or 50),
        "atr_pct": float(analysis.get("atr_pct", 0) or 0),
        "oi_change_pct": float(analysis.get("oi_change", 0) or 0),
        "funding_rate": float(analysis.get("funding_rate", 0) or 0),
        "macd_histogram": float(analysis.get("macd_histogram", 0) or 0),
        "squeeze": int(analysis.get("squeeze", 0) or 0),
    }


# === MAIN ===
def main():
    print(f"🔍 Scanner v8 Starting...")
    tok_ok = bool(TELEGRAM_BOT_TOKEN and str(TELEGRAM_BOT_TOKEN).strip())
    ch_ok = bool(TELEGRAM_CHANNEL and str(TELEGRAM_CHANNEL).strip())
    try:
        _pst = POST_SIGNALS_TO_TELEGRAM
    except Exception:
        _pst = True
    print(f"  Telegram: POST_SIGNALS_TO_TELEGRAM={_pst}, token={'ok' if tok_ok else 'MISSING'}, chat_id={'ok' if ch_ok else 'MISSING'}")
    
    balance = get_balance()
    try:
        if (
            getattr(config, 'TELEGRAM_PING_ON_SCANNER_START', False)
            and _pst
            and tok_ok
            and ch_ok
        ):
            from telegram_util import send_telegram_message

            send_telegram_message(
                f'Neko scanner v8 tick: balance ${balance:.2f} (ping; disable TELEGRAM_PING_ON_SCANNER_START in config)',
                prefer_markdown=False,
            )
            print('  Telegram: start ping sent')
    except Exception as e:
        print(f'  Telegram: start ping failed: {e}')
    positions = get_positions()
    open_count = len(positions)
    
    # Detect manually closed positions
    try:
        positions_file = os.path.join(script_dir, '.positions_sl_tp.json')
        if os.path.exists(positions_file):
            with open(positions_file, 'r') as f:
                saved_positions = json.load(f)
            
            current_symbols = {p.get('symbol') for p in positions}
            
            for sym in list(saved_positions.keys()):
                if sym not in current_symbols:
                    # Position was closed (manually or auto)
                    print(f"  📝 Detected closed: {sym}")
                    # Add to recently closed
                    with open('.recently_closed', 'a') as f:
                        f.write(f"{sym},{int(time.time())}\n")
                    # Remove from saved
                    del saved_positions[sym]
            
            # Update saved positions
            with open(positions_file, 'w') as f:
                json.dump(saved_positions, f)
    except Exception as e:
        print(f"  Warning: Could not check closed positions: {e}")
    
    print(f"  Balance: ${balance:.2f}")
    print(f"  Open: {open_count}/{MAX_POSITIONS}")
    
    # Check margin risk before trading
    risk = check_margin_risk()
    print(f"  📊 Risk: {risk['margin_pct']:.1f}% margin used")
    
    if not risk['safe_to_trade']:
        if getattr(config, "SCANNER_RISK_ONLY_MAX_POSITIONS", True):
            print(
                f"⚠️ Лимит позиций — новые входы отключены ({risk['positions']}/{MAX_POSITIONS}). "
                f"(Маржа {risk['margin_pct']:.1f}% не блокирует при SCANNER_RISK_ONLY_MAX_POSITIONS.)"
            )
        else:
            print(f"⚠️ HIGH RISK - Not trading!")
            print(f"   Margin: {risk['margin_pct']:.1f}% (max {MAX_MARGIN_PERCENT}%)")
            print(f"   Positions: {risk['positions']}/{MAX_POSITIONS}")
        return

    if open_count >= MAX_POSITIONS:
        print("⚠️ Max positions reached - waiting...")
        return
    
    # Get all tickers
    tickers = get_24h_tickers()
    stats = {t['symbol']: t for t in tickers if t['symbol'].endswith('USDT')}
    
    # Sort by price change
    movers = [(s, float(t['priceChangePercent'])) for s, t in stats.items()]
    movers.sort(key=lambda x: x[1], reverse=True)
    
    print(f"  Found {len(movers)} symbols")
    
    # Load posted signals (to avoid duplicates)
    try:
        with open('.posted_signals', 'r') as f:
            posted = set(f.read().strip().split(','))
    except:
        posted = set()
    
    # Load recently closed positions (skip re-entry for 24h)
    recently_closed = set()
    try:
        with open('.recently_closed', 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    parts = line.split(',')
                    if len(parts) >= 2:
                        symbol, timestamp = parts[0], int(parts[1])
                        # Skip if closed in last 24 hours
                        if time.time() - timestamp < 86400:  # 24 hours
                            recently_closed.add(symbol)
    except:
        pass
    
    # Список монет: весь ALL_COINS (по умолчанию) или только SAFE — см. config.SCANNER_SYMBOL_UNIVERSE
    try:
        _univ = str(getattr(config, "SCANNER_SYMBOL_UNIVERSE", "all") or "all").strip().lower()
        _coin_set = ALL_COINS if _univ in ("all", "full", "*") else SAFE_COINS
    except Exception:
        _coin_set = SAFE_COINS
    movers_filtered = [(s, p) for s, p in movers if s in _coin_set]
    try:
        _max_sym = int(getattr(config, "SCANNER_MAX_SYMBOLS_PER_PASS", 120))
    except (TypeError, ValueError):
        _max_sym = 120
    _max_sym = max(1, min(500, _max_sym))

    # Моментум по выбранному universe (не только «безопасные»)
    for symbol, change in movers_filtered[:_max_sym]:
        if open_count >= MAX_POSITIONS:
            break
        
        # Skip if already has position
        if any(p.get('symbol') == symbol for p in positions):
            continue
        
        # Skip if token is on delisting blocklist
        if DELISTING_CHECK and is_token_blocked(symbol):
            print(f"  ⚠️ Skipping {symbol} - on delisting blocklist")
            continue
        
        # Skip if recently closed (avoid re-entry)
        if symbol in recently_closed:
            print(f"  Skipping {symbol} - recently closed")
            continue
        
        print(f"  Checking {symbol} ({change:.1f}%)...", end=" ")
        
        try:
            analysis = analyze_symbol(symbol, stats)
            if analysis:
                print(f"✅ SIGNAL! {analysis['direction']}")
                macd_h = analysis.get("macd_histogram", 0)
                squeeze = analysis.get("squeeze", 0)
                oi_ch = analysis.get("oi_change", 0)
                vol_r = analysis.get("vol_ratio", 1)
                print(f"      -> indicators: MACD={macd_h:+.4f} squeeze={squeeze} OI={oi_ch:+.1f}% vol={vol_r:.1f}x")
                
                # Send signal to Telegram IMMEDIATELY (even before order execution)
                if POST_SIGNALS_TO_TELEGRAM:
                    try:
                        # Get improved score data if available
                        final_score = analysis.get('final_score', analysis.get('runner_score', 0))
                        adx_info = analysis.get('adx_data', {})
                        btc_info = analysis.get('btc_correlation', {})
                        session_info = analysis.get('session_data', {})
                        
                        eff_dir = _scanner_effective_direction(analysis["direction"])
                        msg = f"🐱 Neko Scanner Signal v2.0!\n\n"
                        msg += f"📊 {analysis['symbol']} — открытие: {eff_dir}"
                        if config.invert_signals_enabled():
                            msg += f" (анализ: {analysis['direction']})"
                        msg += f"\n"
                        msg += f"💰 Entry: ${analysis['current']:.6f}\n"
                        msg += f"📈 Change: {analysis['price_change']:+.1f}%\n"
                        msg += f"📊 Score: {final_score:.1f}"
                        if adx_info:
                            msg += f" | ADX: {adx_info.get('adx', 0):.1f} ({adx_info.get('trend_strength', '?')})"
                        msg += f"\n"
                        msg += f"🔊 Vol: {vol_r:.1f}x | OI: {oi_ch:+.1f}%\n"
                        if btc_info:
                            corr = btc_info.get('correlation', 0)
                            btc_trend = btc_info.get('btc_trend', '?')
                            aligned = '✅' if btc_info.get('aligned', False) else '❌'
                            msg += f"₿ BTC: {btc_trend} | Corr: {corr:.2f} {aligned}\n"
                        if session_info:
                            msg += f"🕐 Session: {session_info.get('session', '?')}\n"
                        msg += f"\n{_telegram_sl_tp_lines(analysis)}"
                        msg += f"\n#Signals #{analysis['symbol'].replace('USDT','')}"
                        if send_telegram(msg):
                            print(f"  📤 Sent to Telegram (v2.0)")
                        else:
                            print(f"  ⚠️ Telegram: не удалось отправить сигнал v2.0 (см. [telegram] в логе)")
                    except Exception as e:
                        print(f"  ⚠️ Telegram error: {e}")
                
                # Маржа = ENTRY_PERCENT от фикс. депозита (MARGIN_DEPOSIT_USD)
                try:
                    dep_cfg = float(getattr(config, "MARGIN_DEPOSIT_USD", 0.0) or 0.0)
                except (TypeError, ValueError):
                    dep_cfg = 0.0
                deposit_usd = dep_cfg if dep_cfg > 0 else float(balance)
                if dep_cfg <= 0:
                    print(
                        "  ⚠️ Задайте MARGIN_DEPOSIT_USD в .env (USDT) — иначе маржа от текущего баланса."
                    )
                margin_target_usd = config.entry_margin_cap_usd(deposit_usd)
                if margin_target_usd <= 0:
                    print(f"  Skipped {symbol}: нулевая целевая маржа")
                    continue

                # Get step size for proper quantity formatting
                try:
                    info_r = requests.get(f'{BASE_URL}/fapi/v1/exchangeInfo', timeout=10)
                    step_size = 0.001
                    min_qty = 0.001
                    min_notional = 5.0
                    for s in info_r.json().get('symbols', []):
                        if s['symbol'] == symbol:
                            for f in s.get('filters', []):
                                if f.get('filterType') == 'LOT_SIZE':
                                    step_size = float(f.get('stepSize', 0.001))
                                    min_qty = float(f.get('minQty', 0.001))
                                elif f.get('filterType') == 'MIN_NOTIONAL':
                                    min_notional = float(f.get('notional', 5))
                            break
                except Exception:
                    step_size = 0.001
                    min_notional = 5.0
                
                quantity, notional, qty_err = config.compute_qty_strict_margin_cap(
                    margin_target_usd,
                    float(LEVERAGE),
                    float(analysis["current"]),
                    step_size,
                    min_qty,
                    min_notional,
                )
                if qty_err or quantity is None:
                    print(f"  Skipped {symbol}: {qty_err or 'qty'}")
                    continue

                lev_f = float(LEVERAGE) if LEVERAGE else 1.0
                margin_actual = notional / lev_f if lev_f > 0 else notional
                pct_dep = (margin_actual / deposit_usd * 100.0) if deposit_usd > 1e-12 else 0.0
                pct_nom_dep = (notional / deposit_usd * 100.0) if deposit_usd > 1e-12 else 0.0
                print(
                    f"  📏 Size: депозит ${deposit_usd:.2f} | маржа ${margin_actual:.2f} ({pct_dep:.2f}% деп.) | "
                    f"цель ${margin_target_usd:.2f} ({ENTRY_PERCENT}% от деп.) | "
                    f"номинал ${notional:.2f} (~{pct_nom_dep:.0f}% деп. по номиналу) @ {LEVERAGE}x"
                )

                set_leverage(symbol, LEVERAGE)
                
                # ── EXPERIMENTAL: INVERT SIGNALS ─────────────────────────────
                # Если invert_signals_enabled(), открываем противоположную позицию
                original_direction = analysis['direction']
                if config.invert_signals_enabled():
                    inverted_direction = "SHORT" if original_direction == "LONG" else "LONG"
                    print(f"  ⚠️  INVERTED: {original_direction} → {inverted_direction}")
                    side = "BUY" if inverted_direction == "LONG" else "SELL"
                    # Recalculate SL/TP for opposite direction
                    atr = analysis.get('atr', analysis['current'] * 0.02)
                    if inverted_direction == "LONG":
                        sl_price = analysis['current'] - (atr * 2)
                        tp_price = analysis['current'] + (atr * 5)
                    else:  # SHORT
                        sl_price = analysis['current'] + (atr * 2)
                        tp_price = analysis['current'] - (atr * 5)
                    sl_price = config.clamp_sl_price_to_leverage(inverted_direction, analysis["current"], sl_price)
                    print(f"      Inverted SL/TP: SL=${sl_price:.6f}, TP=${tp_price:.6f}")
                else:
                    side = "BUY" if original_direction == "LONG" else "SELL"
                    sl_price = analysis.get('sl')
                    tp_price = analysis.get('tp1')
                # ──────────────────────────────────────────────────────────────
                
                # Place order with SL/TP
                result = place_order_with_sl_tp(symbol, side, quantity, sl_price, tp_price)
                
                order_id = result.get('orderId', 'N/A')
                status = result.get('status', 'UNKNOWN')
                actual_dir = "LONG" if side == "BUY" else "SHORT"
                
                # Only post if order succeeded (has valid orderId)
                if order_id and order_id != 'N/A':
                    if symbol in posted:
                        print(f"  (already posted)")
                    else:
                        msg = format_signal(analysis, stats)
                        msg += f"\n✅ Исполнено: {actual_dir}"
                        if config.invert_signals_enabled():
                            msg += f" (анализ: {analysis['direction']})"
                        msg += f"\n🛡 SL по fill: ${sl_price:.6f}"
                        if not getattr(config, "SCANNER_USE_TRAIL_EXIT", True):
                            msg += f"\n📈 TP на бирже: ${tp_price:.6f}"
                        msg += f"\n📋 Order ID: {order_id} | Status: {status}"
                        
                        if send_telegram(msg):
                            print(f"  Order: {order_id} | Posted to Telegram")
                        else:
                            print(f"  Order: {order_id} | Telegram: отправка не удалась")
                        
                        # Save SL/TP for price monitor
                        try:
                            positions_file = os.path.join(script_dir, '.positions_sl_tp.json')
                            positions_data = {}
                            if os.path.exists(positions_file):
                                with open(positions_file, 'r') as f:
                                    positions_data = json.load(f)
                            positions_data[symbol] = {
                                'entry': analysis['current'],
                                'sl': sl_price,
                                'tp1': tp_price,
                                'side': side,
                                'opened_at': datetime.now().isoformat(),
                                'tag': position_tags.TAG_SCANNER_V8,
                                'pos_dir': actual_dir,
                            }
                            try:
                                position_tags.set_tag(
                                    symbol, actual_dir, position_tags.TAG_SCANNER_V8, "scanner_v8"
                                )
                            except Exception:
                                pass
                            with open(positions_file, 'w') as f:
                                json.dump(positions_data, f)
                            print(f"  Saved SL/TP: SL={sl_price}, TP={tp_price}")
                        except Exception as e:
                            print(f"  Warning: Could not save SL/TP: {e}")
                        
                        posted.add(symbol)
                        with open('.posted_signals', 'w') as f:
                            f.write(','.join(posted))

                        try:
                            _fs = analysis.get("final_score", analysis.get("runner_score", 0))
                            sig_score = int(round(float(_fs))) if _fs is not None else 0
                        except Exception:
                            sig_score = 0
                        try:
                            signals_table.log_signal(
                                symbol,
                                actual_dir,
                                float(analysis["current"]),
                                float(sl_price),
                                float(tp_price),
                                _signal_indicators_from_analysis(analysis),
                                sig_score,
                                opened_position=True,
                                category="SAFE" if symbol in SAFE_COINS else "OTHER",
                                source="scanner_v8",
                            )
                        except Exception as ex_sig:
                            print(f"  Warning: signals_table: {ex_sig}")

                        open_count += 1
                else:
                    if result.get('code'):
                        print(f"  Order failed: {result.get('msg', status)}")
                    else:
                        print(f"  Order failed: {status}")
            else:
                print("no signal")
        except Exception as e:
            print(f"error: {e}")
    
    print(f"\n✅ Scan complete!")

if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            print(f"Error: {e}")
        print("Sleeping 60s before next scan...")
        time.sleep(60)

