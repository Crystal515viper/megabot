"""SSE stream router for real-time position updates."""
import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
import redis.asyncio as redis

from src.api.schemas import StreamPositionUpdate, AccountSide, PositionStatus


router = APIRouter(prefix="/stream", tags=["Stream"])


async def get_redis_client() -> redis.Redis:
    """Get Redis client dependency."""
    return redis.from_url(
        "redis://localhost:6379/0",
        encoding="utf-8",
        decode_responses=True
    )


async def position_stream_generator(
    request: Request,
    redis_client: redis.Redis,
) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for position updates.
    
    Listens to Redis pub/sub channel for position changes
    and streams them to the client in real-time.
    """
    pubsub = redis_client.pubsub()
    channel = "stream:positions"
    
    await pubsub.subscribe(channel)
    
    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break
            
            # Wait for messages with timeout to check disconnect
            message = await asyncio.wait_for(
                pubsub.get_message(ignore_subscribe_messages=True),
                timeout=30.0
            )
            
            if message and message["type"] == "message":
                data = json.loads(message["data"])
                
                # Format as SSE event
                event_data = {
                    "position_id": data.get("position_id"),
                    "symbol": data.get("symbol"),
                    "side": data.get("side"),
                    "current_price": str(data.get("current_price")),
                    "unrealized_pnl": str(data.get("unrealized_pnl")),
                    "trailing_stop_price": str(data.get("trailing_stop_price")) 
                        if data.get("trailing_stop_price") else None,
                    "status": data.get("status"),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                
                yield f"data: {json.dumps(event_data)}\n\n"
            
            # Send heartbeat every 30 seconds to keep connection alive
            yield f": heartbeat\n\n"
    
    except asyncio.TimeoutError:
        # Normal timeout, will reconnect
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


@router.get("/positions")
async def stream_positions(
    request: Request,
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Server-Sent Events (SSE) stream for real-time position updates.
    
    Streams:
    - Current price updates
    - Unrealized PnL changes
    - Trailing stop adjustments
    - Position status changes
    
    Client example (JavaScript):
    ```javascript
    const eventSource = new EventSource('/api/v1/stream/positions');
    
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('Position update:', data);
        // Update UI with data.position_id, data.unrealized_pnl, etc.
    };
    
    eventSource.onerror = (error) => {
        console.error('SSE Error:', error);
        eventSource.close();
    };
    ```
    
    React example:
    ```javascript
    useEffect(() => {
        const eventSource = new EventSource('/api/v1/stream/positions');
        
        eventSource.addEventListener('message', (event) => {
            const data = JSON.parse(event.data);
            setPositions(prev => 
                prev.map(p => p.id === data.position_id ? {...p, ...data} : p)
            );
        });
        
        return () => eventSource.close();
    }, []);
    ```
    """
    return StreamingResponse(
        position_stream_generator(request, redis_client),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/positions/publish")
async def publish_position_update(
    position_id: int,
    symbol: str,
    side: str,
    current_price: float,
    unrealized_pnl: float,
    trailing_stop_price: Optional[float] = None,
    status: str = "OPEN",
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Publish a position update to the SSE stream.
    
    This endpoint is called by bots when position state changes.
    Normally not called directly by clients.
    """
    message = {
        "position_id": position_id,
        "symbol": symbol,
        "side": side,
        "current_price": current_price,
        "unrealized_pnl": unrealized_pnl,
        "trailing_stop_price": trailing_stop_price,
        "status": status,
    }
    
    await redis_client.publish("stream:positions", json.dumps(message))
    
    return {"status": "published", "message": message}
