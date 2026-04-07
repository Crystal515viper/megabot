"""
Mock Exchange Server for Local Testing.

This module provides a simple mock exchange server for testing bots
without connecting to real exchanges. Simulates order placement,
fills, and price ticks.

Usage:
    python -m src.bots.mock_exchange_server
"""

import asyncio
import json
import random
import time
from typing import Dict, Any, Optional
from decimal import Decimal

from loguru import logger


class MockExchange:
    """
    Simulates exchange behavior for paper trading tests.
    
    Features:
    - Order placement with simulated fills
    - Price ticker simulation (random walk)
    - Account balance tracking
    - Order book simulation
    """
    
    def __init__(self, initial_balance: float = 10000.0):
        self.balance = initial_balance
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.prices: Dict[str, float] = {
            "BTC/USDT": 45000.0,
            "ETH/USDT": 3000.0,
            "SOL/USDT": 100.0
        }
        self.order_counter = 0
        
        logger.info(f"[MockExchange] Initialized with balance: ${initial_balance}")
    
    async def load_markets(self):
        """Simulate loading market data."""
        await asyncio.sleep(0.1)
        logger.info("[MockExchange] Markets loaded")
    
    async def create_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float
    ) -> Dict[str, Any]:
        """
        Create a limit order (simulated).
        
        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            side: "buy" or "sell"
            amount: Order size
            price: Limit price
            
        Returns:
            Order dict with id, status, filled, average
        """
        self.order_counter += 1
        order_id = f"mock_{self.order_counter}_{time.time()}"
        
        # Simulate partial fill probability
        fill_probability = 0.9  # 90% chance of immediate fill
        
        if random.random() < fill_probability:
            # Immediate fill
            order = {
                'id': order_id,
                'symbol': symbol,
                'side': side,
                'type': 'limit',
                'status': 'closed',
                'amount': amount,
                'filled': amount,
                'remaining': 0,
                'price': price,
                'average': price * (1 + random.uniform(-0.0005, 0.0005)),  # Slight slippage
                'timestamp': time.time() * 1000
            }
            logger.info(f"[MockExchange] Order {order_id} filled: {amount} {symbol} @ {order['average']}")
        else:
            # Not filled immediately
            order = {
                'id': order_id,
                'symbol': symbol,
                'side': side,
                'type': 'limit',
                'status': 'open',
                'amount': amount,
                'filled': 0,
                'remaining': amount,
                'price': price,
                'average': None,
                'timestamp': time.time() * 1000
            }
            logger.warning(f"[MockExchange] Order {order_id} not filled yet")
        
        self.orders[order_id] = order
        return order
    
    async def create_market_order(
        self,
        symbol: str,
        side: str,
        amount: float
    ) -> Dict[str, Any]:
        """
        Create a market order (always fills immediately).
        
        Args:
            symbol: Trading pair
            side: "buy" or "sell"
            amount: Order size
            
        Returns:
            Order dict with fill information
        """
        current_price = self.prices.get(symbol, 100.0)
        
        # Add some slippage for market orders
        slippage = random.uniform(0.0001, 0.001)
        fill_price = current_price * (1 + slippage if side == "buy" else 1 - slippage)
        
        self.order_counter += 1
        order_id = f"mock_market_{self.order_counter}"
        
        order = {
            'id': order_id,
            'symbol': symbol,
            'side': side,
            'type': 'market',
            'status': 'closed',
            'amount': amount,
            'filled': amount,
            'remaining': 0,
            'price': fill_price,
            'average': fill_price,
            'timestamp': time.time() * 1000
        }
        
        logger.info(f"[MockExchange] Market order {order_id} filled: {amount} {symbol} @ {fill_price}")
        return order
    
    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel an open order."""
        if order_id in self.orders:
            order = self.orders[order_id]
            order['status'] = 'canceled'
            order['remaining'] = order['amount'] - order['filled']
            logger.info(f"[MockExchange] Order {order_id} canceled")
            return order
        else:
            raise Exception(f"Order {order_id} not found")
    
    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch latest ticker with simulated price movement.
        
        Returns ticker with last, bid, ask, high, low, volume.
        """
        if symbol not in self.prices:
            self.prices[symbol] = 100.0
        
        # Random walk price movement
        change_pct = random.uniform(-0.002, 0.003)  # -0.2% to +0.3%
        self.prices[symbol] *= (1 + change_pct)
        
        price = self.prices[symbol]
        
        ticker = {
            'symbol': symbol,
            'last': price,
            'bid': price * 0.9999,
            'ask': price * 1.0001,
            'high': price * 1.01,
            'low': price * 0.99,
            'volume': random.uniform(1000, 10000),
            'timestamp': time.time() * 1000
        }
        
        return ticker
    
    async def close(self):
        """Close exchange connection."""
        logger.info("[MockExchange] Connection closed")


async def run_mock_server():
    """
    Run standalone mock server for integration testing.
    
    This simulates Redis queue consumption and order execution.
    """
    import redis.asyncio as redis
    
    exchange = MockExchange()
    await exchange.load_markets()
    
    redis_client = redis.from_url("redis://localhost:6379", decode_responses=True)
    
    logger.info("[MockServer] Starting mock exchange server...")
    logger.info("[MockServer] Listening on queue:signals_long and queue:signals_short")
    
    try:
        while True:
            # Check both queues
            for queue in ["queue:signals_long", "queue:signals_short"]:
                result = await redis_client.blpop(queue, timeout=1)
                
                if result:
                    _, message = result
                    signal = json.loads(message)
                    logger.info(f"[MockServer] Received signal: {signal}")
                    
                    # Simulate order processing
                    symbol = signal.get('symbol', 'BTC/USDT')
                    side = "buy" if "long" in queue else "sell"
                    price = signal.get('price', exchange.prices.get(symbol, 100))
                    amount = signal.get('metadata', {}).get('amount', 0.1)
                    
                    order = await exchange.create_limit_order(symbol, side, amount, price)
                    logger.info(f"[MockServer] Order result: {order}")
                    
    except KeyboardInterrupt:
        logger.info("[MockServer] Stopped by user")
    finally:
        await exchange.close()
        await redis_client.close()


if __name__ == "__main__":
    # Example usage
    async def demo():
        exchange = MockExchange()
        await exchange.load_markets()
        
        print("\n=== Mock Exchange Demo ===\n")
        
        # Test limit order
        print("1. Creating limit order...")
        order = await exchange.create_limit_order("BTC/USDT", "buy", 0.1, 45000)
        print(f"   Order: {order}\n")
        
        # Test market order
        print("2. Creating market order...")
        order = await exchange.create_market_order("ETH/USDT", "sell", 1.0)
        print(f"   Order: {order}\n")
        
        # Test ticker
        print("3. Fetching tickers...")
        for i in range(3):
            ticker = await exchange.fetch_ticker("BTC/USDT")
            print(f"   Tick {i+1}: BTC @ {ticker['last']:.2f}")
            await asyncio.sleep(0.5)
        
        await exchange.close()
        print("\n=== Demo Complete ===\n")
    
    asyncio.run(demo())
