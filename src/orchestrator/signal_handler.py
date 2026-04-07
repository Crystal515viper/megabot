"""Signal handler module for processing trading signals."""

import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum

from loguru import logger
import redis.asyncio as redis

from src.risk.volatility_filter import should_trade, calculate_atr, calculate_zscore, calculate_snr
from src.risk.leverage_calculator import calculate_leverage
from src.core.trailing_stop import TrailingStopManager
from src.db.session import get_async_session
from src.db.crud import create_signal, create_position


class SignalDecision(Enum):
    """Decision outcomes for signal processing."""
    ACCEPTED = "accepted"
    REJECTED_VOLATILITY = "rejected_volatility"
    REJECTED_SNR = "rejected_snr"
    REJECTED_ERROR = "rejected_error"


@dataclass
class SignalInput:
    """Input signal data structure."""
    symbol: str
    timestamp: float
    price: float
    raw_signal: float  # -1.0 to 1.0 (short to long)
    metadata: Dict[str, Any]
    # Optional historical data for calculations
    prices_history: Optional[list[float]] = None
    volumes_history: Optional[list[float]] = None


@dataclass
class SignalOutput:
    """Processed signal output."""
    decision: SignalDecision
    reason: str
    leverage: Optional[float] = None
    position_side: Optional[str] = None
    signal_id: Optional[int] = None
    queue_name: Optional[str] = None


class CircuitBreaker:
    """Circuit breaker for bot health monitoring."""
    
    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds
        self.last_heartbeat: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
    
    async def record_heartbeat(self, bot_id: str):
        """Record bot heartbeat."""
        async with self._lock:
            self.last_heartbeat[bot_id] = datetime.now(timezone.utc)
    
    async def is_healthy(self, bot_id: str) -> bool:
        """Check if bot is healthy (responded within timeout)."""
        async with self._lock:
            last_seen = self.last_heartbeat.get(bot_id)
            if last_seen is None:
                return False
            elapsed = (datetime.now(timezone.utc) - last_seen).total_seconds()
            return elapsed <= self.timeout_seconds
    
    async def get_unhealthy_bots(self) -> list[str]:
        """Get list of unhealthy bots."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            unhealthy = []
            for bot_id, last_seen in self.last_heartbeat.items():
                if (now - last_seen).total_seconds() > self.timeout_seconds:
                    unhealthy.append(bot_id)
            return unhealthy


class SignalHandler:
    """Main signal processing handler."""
    
    def __init__(self, redis_url: str, retry_ttl_seconds: int = 300):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.circuit_breaker = CircuitBreaker(timeout_seconds=10.0)
        self.retry_ttl_seconds = retry_ttl_seconds
        self.trailing_manager = TrailingStopManager()
    
    async def connect(self):
        """Initialize Redis connection."""
        self.redis_client = redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("Redis connection established")
    
    async def disconnect(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")
    
    async def process_signal(self, signal: SignalInput) -> SignalOutput:
        """
        Process incoming signal through the pipeline:
        1. Validate input
        2. Apply volatility filters
        3. Calculate leverage
        4. Store in database
        5. Publish to Redis queue
        
        Returns: SignalOutput with decision and routing info
        """
        try:
            # Step 1: Validate input
            if not self._validate_signal(signal):
                return SignalOutput(
                    decision=SignalDecision.REJECTED_ERROR,
                    reason="Invalid signal data"
                )
            
            # Step 2: Apply volatility filters
            filter_result = self._apply_filters(signal)
            if not filter_result["should_trade"]:
                reason = filter_result.get("reason", "Filter criteria not met")
                if "volatility" in reason.lower():
                    decision = SignalDecision.REJECTED_VOLATILITY
                elif "snr" in reason.lower():
                    decision = SignalDecision.REJECTED_SNR
                else:
                    decision = SignalDecision.REJECTED_ERROR
                
                logger.warning(
                    f"Signal rejected for {signal.symbol}: {reason}",
                    extra={"symbol": signal.symbol, "price": signal.price}
                )
                return SignalOutput(
                    decision=decision,
                    reason=reason
                )
            
            # Step 3: Calculate leverage
            leverage = calculate_leverage(
                risk_roi=signal.metadata.get("risk_roi", 0.02),
                atr_percent=filter_result["atr_percent"],
                snr=filter_result["snr"],
                k_factor=signal.metadata.get("k_factor", 1.5)
            )
            
            # Determine position side
            position_side = "LONG" if signal.raw_signal > 0 else "SHORT"
            queue_name = f"queue:signals_{position_side.lower()}"
            
            # Step 4: Store in database
            async with get_async_session() as session:
                signal_record = await create_signal(
                    session=session,
                    symbol=signal.symbol,
                    timestamp=datetime.fromtimestamp(signal.timestamp, tz=timezone.utc),
                    price=signal.price,
                    raw_signal=signal.raw_signal,
                    metadata=signal.metadata,
                    atr=filter_result["atr"],
                    zscore=filter_result["zscore"],
                    snr=filter_result["snr"],
                    calculated_leverage=leverage,
                )
                signal_id = signal_record.id
                
                # Create initial position record if leverage > 0
                if leverage > 0:
                    position = await create_position(
                        session=session,
                        signal_id=signal_id,
                        account_id=signal.metadata.get("account_id", 1),
                        symbol=signal.symbol,
                        side=position_side,
                        entry_price=signal.price,
                        leverage=leverage,
                        status="OPEN",
                    )
                    logger.info(
                        f"Position created: {position_side} {signal.symbol} @ {signal.price} x{leverage}",
                        extra={"signal_id": signal_id, "position_id": position.id}
                    )
            
            # Step 5: Publish to Redis queue
            await self._publish_to_queue(queue_name, {
                "signal_id": signal_id,
                "symbol": signal.symbol,
                "side": position_side,
                "price": signal.price,
                "leverage": leverage,
                "timestamp": signal.timestamp,
                "metadata": signal.metadata,
            })
            
            logger.info(
                f"Signal accepted and published to {queue_name}",
                extra={
                    "signal_id": signal_id,
                    "symbol": signal.symbol,
                    "leverage": leverage,
                }
            )
            
            return SignalOutput(
                decision=SignalDecision.ACCEPTED,
                reason="Signal processed successfully",
                leverage=leverage,
                position_side=position_side,
                signal_id=signal_id,
                queue_name=queue_name,
            )
            
        except Exception as e:
            logger.error(f"Error processing signal: {e}", exc_info=True)
            return SignalOutput(
                decision=SignalDecision.REJECTED_ERROR,
                reason=f"Processing error: {str(e)}"
            )
    
    def _validate_signal(self, signal: SignalInput) -> bool:
        """Validate signal input data."""
        if not signal.symbol or not isinstance(signal.symbol, str):
            return False
        if not isinstance(signal.timestamp, (int, float)) or signal.timestamp <= 0:
            return False
        if not isinstance(signal.price, (int, float)) or signal.price <= 0:
            return False
        if not isinstance(signal.raw_signal, (int, float)) or signal.raw_signal < -1.0 or signal.raw_signal > 1.0:
            return False
        return True
    
    def _apply_filters(self, signal: SignalInput) -> Dict[str, Any]:
        """
        Apply volatility and quality filters.
        Returns dict with should_trade, atr, zscore, snr, and reason.
        """
        result = {
            "should_trade": False,
            "atr": 0.0,
            "atr_percent": 0.0,
            "zscore": 0.0,
            "snr": 0.0,
            "reason": "",
        }
        
        # Need historical data for calculations
        if not signal.prices_history or len(signal.prices_history) < 14:
            result["reason"] = "Insufficient price history for analysis"
            return result
        
        prices = signal.prices_history
        
        # Calculate ATR (CONFIG_REF: default period=14)
        atr = calculate_atr(prices, period=14)
        atr_percent = (atr / signal.price) * 100
        result["atr"] = atr
        result["atr_percent"] = atr_percent
        
        # Calculate Z-score (CONFIG_REF: default period=20)
        zscore = calculate_zscore(prices, period=20)
        result["zscore"] = zscore
        
        # Calculate SNR using FFT (CONFIG_REF: requires scipy)
        snr = calculate_snr(prices)
        result["snr"] = snr
        
        # Apply filtering logic
        should, reason = should_trade({
            "atr": atr,
            "atr_percent": atr_percent,
            "zscore": zscore,
            "snr": snr,
            "price": signal.price,
        })
        
        result["should_trade"] = should
        result["reason"] = reason
        
        return result
    
    async def _publish_to_queue(self, queue_name: str, message: Dict[str, Any]):
        """Publish message to Redis queue with retry logic."""
        if not self.redis_client:
            raise RuntimeError("Redis client not initialized")
        
        try:
            # Use RPUSH for simple queue (BLPOP on consumer side)
            message_json = json.dumps(message, default=str)
            await self.redis_client.rpush(queue_name, message_json)
            logger.debug(f"Published to {queue_name}: {message_json}")
            
        except redis.RedisError as e:
            logger.error(f"Redis error publishing to {queue_name}: {e}")
            # Publish to retry queue with TTL
            retry_queue = "queue:retry"
            message["original_queue"] = queue_name
            message["retry_timestamp"] = datetime.now(timezone.utc).isoformat()
            message_json = json.dumps(message, default=str)
            await self.redis_client.rpush(retry_queue, message_json)
            # Set TTL on the retry queue key (note: TTL on list is tricky, using hash instead)
            retry_key = f"retry:{queue_name}:{message.get('signal_id', 'unknown')}"
            await self.redis_client.setex(retry_key, self.retry_ttl_seconds, message_json)
            logger.warning(f"Message sent to retry queue with TTL {self.retry_ttl_seconds}s")
    
    async def check_bot_health_and_retry(self):
        """Check bot health and move signals to retry queue if needed."""
        unhealthy_bots = await self.circuit_breaker.get_unhealthy_bots()
        
        for bot_id in unhealthy_bots:
            bot_queue = f"queue:signals_{bot_id}"
            # Move pending signals to retry queue
            # Implementation depends on queue structure
            logger.warning(f"Bot {bot_id} unhealthy, signals may be retried")


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def main():
        handler = SignalHandler(redis_url="redis://localhost:6379")
        await handler.connect()
        
        # Example signal
        signal = SignalInput(
            symbol="BTCUSDT",
            timestamp=datetime.now(timezone.utc).timestamp(),
            price=45000.0,
            raw_signal=0.75,
            metadata={"account_id": 1, "risk_roi": 0.02, "k_factor": 1.5},
            prices_history=[45000 + i * 10 for i in range(-20, 20)],
            volumes_history=[1000 + i * 50 for i in range(40)],
        )
        
        result = await handler.process_signal(signal)
        print(f"Decision: {result.decision}, Reason: {result.reason}")
        
        await handler.disconnect()
    
    asyncio.run(main())
