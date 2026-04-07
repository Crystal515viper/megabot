"""
Base Trading Bot Module.

Abstract base class for Long and Short trading bots.
Implements common logic: Redis subscription, exchange integration,
state machine, heartbeat, error handling, and trailing stop integration.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any, List
from decimal import Decimal
import asyncio
import json
import time
from dataclasses import dataclass, field

import ccxt.pro as ccxt_pro
import redis.asyncio as redis
from loguru import logger

from src.db.session import get_db_session
from src.db.crud import update_position, create_system_log, PositionStatus
from src.core.trailing_stop import TrailingStopManager, TrailingMode
from src.risk.leverage_calculator import calculate_leverage


class PositionState(Enum):
    """State machine for position lifecycle."""
    INIT = "INIT"
    PENDING_FILL = "PENDING_FILL"
    ACTIVE = "ACTIVE"
    TRAILING = "TRAILING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


@dataclass
class BotConfig:
    """Bot configuration from YAML/ENV."""
    bot_name: str
    account_side: str  # LONG or SHORT
    exchange_id: str = "binance"
    api_key: str = ""
    api_secret: str = ""
    sandbox: bool = True
    paper_trading: bool = True
    redis_url: str = "redis://localhost:6379"
    heartbeat_interval: int = 3
    max_retries: int = 3
    retry_base_delay: float = 1.0
    queue_name: str = "queue:signals_long"
    heartbeat_key: str = "bot:long:heartbeat"
    slippage_tolerance: Decimal = Decimal("0.001")  # 0.1%


@dataclass
class TradingPosition:
    """Represents current active position state."""
    signal_id: int
    account_id: int
    symbol: str
    side: str
    entry_price: Decimal
    amount: Decimal
    leverage: int
    state: PositionState = PositionState.INIT
    order_id: Optional[str] = None
    stop_loss_price: Optional[Decimal] = None
    trailing_manager: Optional[TrailingStopManager] = None
    fill_attempts: int = 0
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTradingBot(ABC):
    """
    Abstract base class for trading bots.
    
    Implements:
    - Redis Queue subscription (BLPOP)
    - Exchange integration via ccxt.pro (WebSocket + REST)
    - State machine for position management
    - Heartbeat mechanism
    - Error handling with exponential backoff
    - Trailing stop integration
    - Database logging
    """
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.redis_client: Optional[redis.Redis] = None
        self.exchange: Optional[ccxt_pro.Exchange] = None
        self.current_position: Optional[TradingPosition] = None
        self.db_session = None
        self.running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        logger.info(f"[{config.bot_name}] Initialized with config: {config}")
    
    async def connect(self):
        """Establish connections to Redis and Exchange."""
        # Redis connection
        self.redis_client = redis.from_url(
            self.config.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        logger.info(f"[{self.config.bot_name}] Connected to Redis")
        
        # Exchange connection
        exchange_class = getattr(ccxt_pro, self.config.exchange_id)
        self.exchange = exchange_class({
            'apiKey': self.config.api_key,
            'secret': self.config.api_secret,
            'sandbox': self.config.sandbox,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}  # Futures trading
        })
        
        # Load markets
        await self.exchange.load_markets()
        logger.info(f"[{self.config.bot_name}] Connected to {self.config.exchange_id}")
        
        # DB session
        self.db_session = await anext(get_db_session())
        logger.info(f"[{self.config.bot_name}] Connected to Database")
    
    async def start(self):
        """Main bot loop: subscribe to queue and process signals."""
        await self.connect()
        self.running = True
        
        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"[{self.config.bot_name}] Heartbeat started")
        
        logger.info(f"[{self.config.bot_name}] Listening on queue: {self.config.queue_name}")
        
        try:
            while self.running:
                try:
                    # Block pop from Redis queue (timeout 5s to allow graceful shutdown)
                    result = await self.redis_client.blpop(self.config.queue_name, timeout=5)
                    
                    if result:
                        _, message = result
                        signal_data = json.loads(message)
                        logger.info(f"[{self.config.bot_name}] Received signal: {signal_data}")
                        
                        await self.process_signal(signal_data)
                    else:
                        # Timeout, continue loop
                        continue
                        
                except json.JSONDecodeError as e:
                    logger.error(f"[{self.config.bot_name}] Invalid JSON in queue: {e}")
                    await self._log_error("INVALID_JSON", str(e))
                except Exception as e:
                    logger.error(f"[{self.config.bot_name}] Queue processing error: {e}")
                    await self._log_error("QUEUE_ERROR", str(e))
                    await asyncio.sleep(1)
                    
        finally:
            await self.shutdown()
    
    async def process_signal(self, signal_data: Dict[str, Any]):
        """
        Process incoming signal: validate, create order, manage position.
        
        Flow:
        1. Validate signal
        2. Calculate leverage and position size
        3. Place limit order
        4. Wait for fill
        5. Set stop-loss
        6. Start trailing stop loop
        """
        signal_id = signal_data.get('signal_id')
        account_id = signal_data.get('account_id')
        symbol = signal_data.get('symbol')
        price = Decimal(str(signal_data.get('price')))
        risk_roi = Decimal(str(signal_data.get('risk_roi', '0.02')))
        metadata = signal_data.get('metadata', {})
        
        # Check if already processing a position
        if self.current_position and self.current_position.state != PositionState.CLOSED:
            logger.warning(f"[{self.config.bot_name}] Busy with position {self.current_position.signal_id}, skipping signal {signal_id}")
            await self._log_error("SIGNAL_SKIPPED", f"Busy with position {self.current_position.signal_id}", signal_id)
            return
        
        try:
            # Calculate leverage using risk module
            atr_pct = Decimal(str(metadata.get('atr_pct', '0.02')))
            snr = metadata.get('snr', 1.0)
            leverage = calculate_leverage(risk_roi, atr_pct, snr)
            
            logger.info(f"[{self.config.bot_name}] Calculated leverage: {leverage}x")
            
            # Create position object
            self.current_position = TradingPosition(
                signal_id=signal_id,
                account_id=account_id,
                symbol=symbol,
                side=self.config.account_side,
                entry_price=price,
                amount=Decimal(str(metadata.get('amount', '0.1'))),
                leverage=leverage,
                state=PositionState.INIT,
                metadata=metadata
            )
            
            # Update DB
            await update_position(
                self.db_session,
                signal_id=signal_id,
                status=PositionStatus.OPEN,
                entry_price=float(price),
                leverage=leverage,
                amount=float(self.current_position.amount)
            )
            logger.info(f"[{self.config.bot_name}] Position {signal_id} created in DB")
            
            # Place order
            await self._place_and_monitor_order()
            
        except Exception as e:
            logger.error(f"[{self.config.bot_name}] Signal processing error: {e}")
            await self._log_error("PROCESSING_ERROR", str(e), signal_id)
            self.current_position = None
    
    async def _place_and_monitor_order(self):
        """Place limit order and monitor fill with retry logic."""
        if not self.current_position:
            return
        
        pos = self.current_position
        symbol = pos.symbol
        side = pos.side.lower()
        amount = float(pos.amount)
        price = float(pos.entry_price)
        
        for attempt in range(self.config.max_retries):
            try:
                pos.state = PositionState.PENDING_FILL
                pos.fill_attempts = attempt + 1
                
                logger.info(f"[{self.config.bot_name}] Placing {side} limit order: {amount} {symbol} @ {price} (attempt {attempt+1})")
                
                if self.config.paper_trading:
                    # Simulate order
                    logger.info(f"[{self.config.bot_name}] PAPER TRADING: Simulating order fill")
                    await asyncio.sleep(0.5)  # Simulate network delay
                    order = {
                        'id': f'paper_{time.time()}',
                        'status': 'closed',
                        'filled': amount,
                        'average': price
                    }
                else:
                    # Real order via ccxt
                    order = await self.exchange.create_limit_order(symbol, side, amount, price)
                
                # Check fill status
                if order['status'] == 'closed' or order['filled'] > 0:
                    logger.info(f"[{self.config.bot_name}] Order filled: {order['filled']} @ {order.get('average', price)}")
                    pos.order_id = order['id']
                    pos.state = PositionState.ACTIVE
                    
                    # Set initial stop-loss
                    await self._set_stop_loss(pos)
                    
                    # Start trailing stop
                    await self._start_trailing_loop(pos)
                    return
                else:
                    logger.warning(f"[{self.config.bot_name}] Order not filled, status: {order['status']}")
                    await self._cancel_order(order['id'], symbol)
                    
            except Exception as e:
                logger.error(f"[{self.config.bot_name}] Order attempt {attempt+1} failed: {e}")
                await self._log_error("ORDER_ERROR", str(e), pos.signal_id)
                
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_base_delay * (2 ** attempt)
                    logger.info(f"[{self.config.bot_name}] Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"[{self.config.bot_name}] Max retries reached for signal {pos.signal_id}")
                    pos.state = PositionState.ERROR
                    await self._log_error("MAX_RETRIES", "Order failed after 3 attempts", pos.signal_id)
                    self.current_position = None
    
    async def _set_stop_loss(self, pos: TradingPosition):
        """Set initial stop-loss based on entry price and ATR."""
        atr = Decimal(str(pos.metadata.get('atr', '50')))
        
        if pos.side == "LONG":
            sl_price = pos.entry_price - (atr * Decimal('2'))
        else:  # SHORT
            sl_price = pos.entry_price + (atr * Decimal('2'))
        
        pos.stop_loss_price = sl_price
        logger.info(f"[{self.config.bot_name}] Initial SL set at {sl_price}")
        
        # Initialize trailing stop manager
        pos.trailing_manager = TrailingStopManager(
            mode=TrailingMode.ADAPTIVE,
            initial_sl=sl_price
        )
    
    async def _start_trailing_loop(self, pos: TradingPosition):
        """Monitor price ticks and update trailing stop."""
        pos.state = PositionState.TRAILING
        logger.info(f"[{self.config.bot_name}] Starting trailing stop loop for {pos.signal_id}")
        
        while pos.state == PositionState.TRAILING and self.running:
            try:
                # Fetch latest ticker
                if self.config.paper_trading:
                    # Simulate price movement
                    import random
                    tick_price = pos.entry_price * Decimal(str(1 + random.uniform(-0.001, 0.002)))
                else:
                    ticker = await self.exchange.fetch_ticker(pos.symbol)
                    tick_price = Decimal(str(ticker['last']))
                
                # Update trailing stop
                new_sl = pos.trailing_manager.update_position(
                    current_price=tick_price,
                    side=pos.side
                )
                
                if new_sl != pos.stop_loss_price:
                    old_sl = pos.stop_loss_price
                    pos.stop_loss_price = new_sl
                    logger.info(f"[{self.config.bot_name}] Trailing SL updated: {old_sl} -> {new_sl}")
                    
                    # Update SL order on exchange
                    await self._update_stop_loss_order(pos)
                
                # Check if SL hit
                if self._is_sl_hit(tick_price, pos):
                    logger.info(f"[{self.config.bot_name}] Stop-loss hit at {tick_price}")
                    await self._close_position(pos, "STOP_LOSS")
                    break
                
                await asyncio.sleep(0.5)  # Tick interval
                
            except Exception as e:
                logger.error(f"[{self.config.bot_name}] Trailing loop error: {e}")
                await asyncio.sleep(1)
    
    def _is_sl_hit(self, current_price: Decimal, pos: TradingPosition) -> bool:
        """Check if stop-loss price is hit."""
        if pos.stop_loss_price is None:
            return False
        
        if pos.side == "LONG":
            return current_price <= pos.stop_loss_price
        else:  # SHORT
            return current_price >= pos.stop_loss_price
    
    async def _close_position(self, pos: TradingPosition, reason: str):
        """Close position and update DB."""
        pos.state = PositionState.CLOSING
        logger.info(f"[{self.config.bot_name}] Closing position {pos.signal_id}: {reason}")
        
        try:
            side = "sell" if pos.side == "LONG" else "buy"
            amount = float(pos.amount)
            
            if self.config.paper_trading:
                await asyncio.sleep(0.3)
                close_price = float(pos.entry_price * Decimal('1.01'))  # Simulate
            else:
                # Market order to close
                order = await self.exchange.create_market_order(pos.symbol, side, amount)
                close_price = float(order.get('average', pos.entry_price))
            
            pos.state = PositionState.CLOSED
            
            # Update DB
            await update_position(
                self.db_session,
                signal_id=pos.signal_id,
                status=PositionStatus.CLOSED,
                exit_price=close_price,
                close_reason=reason
            )
            
            logger.info(f"[{self.config.bot_name}] Position {pos.signal_id} closed at {close_price}")
            await self._log_error("POSITION_CLOSED", f"{reason} at {close_price}", pos.signal_id, level="info")
            
        except Exception as e:
            logger.error(f"[{self.config.bot_name}] Close position error: {e}")
            pos.state = PositionState.ERROR
            await self._log_error("CLOSE_ERROR", str(e), pos.signal_id)
        
        finally:
            self.current_position = None
    
    async def _heartbeat_loop(self):
        """Send heartbeat to Redis every N seconds."""
        while self.running:
            try:
                heartbeat_data = {
                    'bot': self.config.bot_name,
                    'side': self.config.account_side,
                    'timestamp': time.time(),
                    'status': 'running',
                    'position': self.current_position.signal_id if self.current_position else None
                }
                await self.redis_client.setex(
                    self.config.heartbeat_key,
                    10,  # TTL 10s
                    json.dumps(heartbeat_data)
                )
            except Exception as e:
                logger.error(f"[{self.config.bot_name}] Heartbeat error: {e}")
            
            await asyncio.sleep(self.config.heartbeat_interval)
    
    async def _cancel_order(self, order_id: str, symbol: str):
        """Cancel order on exchange."""
        if self.config.paper_trading:
            return
        try:
            await self.exchange.cancel_order(order_id, symbol)
        except Exception as e:
            logger.error(f"[{self.config.bot_name}] Cancel order error: {e}")
    
    async def _update_stop_loss_order(self, pos: TradingPosition):
        """Update stop-loss order on exchange (if supported)."""
        # TODO: Implement exchange-specific SL update logic
        pass
    
    async def _log_error(self, error_type: str, message: str, signal_id: Optional[int] = None, level: str = "error"):
        """Log error to system_logs table."""
        try:
            await create_system_log(
                self.db_session,
                service_name=self.config.bot_name,
                log_level=level,
                message=message,
                error_type=error_type,
                signal_id=signal_id
            )
        except Exception as e:
            logger.error(f"[{self.config.bot_name}] Failed to log to DB: {e}")
    
    async def shutdown(self):
        """Graceful shutdown."""
        logger.info(f"[{self.config.bot_name}] Shutting down...")
        self.running = False
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self.current_position and self.current_position.state not in [PositionState.CLOSED, PositionState.ERROR]:
            logger.warning(f"[{self.config.bot_name}] Active position {self.current_position.signal_id} during shutdown!")
        
        if self.exchange:
            await self.exchange.close()
        
        if self.redis_client:
            await self.redis_client.close()
        
        if self.db_session:
            await self.db_session.close()
        
        logger.info(f"[{self.config.bot_name}] Shutdown complete")
    
    @abstractmethod
    def get_queue_name(self) -> str:
        """Return appropriate queue name for bot type."""
        pass
