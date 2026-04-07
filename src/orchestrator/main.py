"""Main entry point for the orchestrator service."""

import os
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
import yaml

from src.orchestrator.signal_handler import SignalHandler, SignalInput, SignalDecision


# Configure structured JSON logging
logger.remove()
logger.add(
    sys.stdout,
    format=json.dumps({
        "timestamp": "{time:YYYY-MM-DDTHH:mm:ss.SSSZ}",
        "level": "{level}",
        "service": "orchestrator",
        "message": "{message}",
        "extra": "{extra}",
    }),
    level=os.getenv("LOG_LEVEL", "INFO"),
    serialize=True,
)

# Global signal handler instance
signal_handler: Optional[SignalHandler] = None


def load_config() -> Dict[str, Any]:
    """Load configuration from YAML file."""
    config_path = os.getenv("ORCHESTRATOR_CONFIG", "config/orchestrator.yaml")
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning(f"Config file {config_path} not found, using defaults")
        return {}
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown."""
    global signal_handler
    
    # Startup
    logger.info("Starting Orchestrator service...")
    
    config = load_config()
    redis_url = os.getenv("REDIS_URL", config.get("redis", {}).get("url", "redis://redis:6379"))
    
    signal_handler = SignalHandler(
        redis_url=redis_url,
        retry_ttl_seconds=config.get("retry_ttl_seconds", 300),
    )
    
    try:
        await signal_handler.connect()
        logger.info("Orchestrator service started successfully")
    except Exception as e:
        logger.error(f"Failed to start orchestrator: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Orchestrator service...")
    if signal_handler:
        await signal_handler.disconnect()
    logger.info("Orchestrator service stopped")


app = FastAPI(
    title="Trading Orchestrator",
    description="Main orchestrator service for trading signals routing",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # CONFIG_REF: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware (basic implementation)."""
    # TODO: Implement proper rate limiting with Redis
    # For now, just pass through
    response = await call_next(request)
    return response


@app.middleware("http")
async def validate_json_middleware(request: Request, call_next):
    """Validate JSON content-type for POST/PUT requests."""
    if request.method in ["POST", "PUT"] and request.url.path.startswith("/api/"):
        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            return JSONResponse(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                content={"error": "Content-Type must be application/json"},
            )
    response = await call_next(request)
    return response


@app.get("/health")
async def health_check():
    """Health check endpoint with dependency status."""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": {
            "redis": "unknown",
            "database": "unknown",
        },
    }
    
    if signal_handler and signal_handler.redis_client:
        try:
            await signal_handler.redis_client.ping()
            health_status["dependencies"]["redis"] = "connected"
        except Exception as e:
            health_status["dependencies"]["redis"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
    
    # TODO: Add database health check
    health_status["dependencies"]["database"] = "not_implemented"
    
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(status_code=status_code, content=health_status)


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "orchestrator",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "signal_webhook": "/api/v1/signal",
        },
    }


@app.post("/api/v1/signal")
async def receive_signal(request: Request):
    """
    Webhook endpoint to receive trading signals from external generator.
    
    Expected JSON body:
    {
        "symbol": "BTCUSDT",
        "timestamp": 1234567890.0,
        "price": 45000.0,
        "raw_signal": 0.75,
        "metadata": {
            "account_id": 1,
            "risk_roi": 0.02,
            "k_factor": 1.5
        },
        "prices_history": [44900, 44950, ...],
        "volumes_history": [1000, 1200, ...]
    }
    
    Returns:
    {
        "accepted": true,
        "decision": "accepted",
        "reason": "Signal processed successfully",
        "leverage": 5.0,
        "position_side": "LONG",
        "signal_id": 123,
        "queue_name": "queue:signals_long"
    }
    """
    if signal_handler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not initialized",
        )
    
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON received: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {str(e)}",
        )
    
    # Validate required fields
    required_fields = ["symbol", "timestamp", "price", "raw_signal"]
    missing_fields = [f for f in required_fields if f not in body]
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required fields: {missing_fields}",
        )
    
    # Create SignalInput object
    signal = SignalInput(
        symbol=body["symbol"],
        timestamp=body["timestamp"],
        price=body["price"],
        raw_signal=body["raw_signal"],
        metadata=body.get("metadata", {}),
        prices_history=body.get("prices_history"),
        volumes_history=body.get("volumes_history"),
    )
    
    logger.info(
        f"Received signal for {signal.symbol}",
        extra={
            "symbol": signal.symbol,
            "price": signal.price,
            "raw_signal": signal.raw_signal,
        },
    )
    
    # Process signal through pipeline
    result = await signal_handler.process_signal(signal)
    
    # Log decision
    logger.info(
        f"Signal decision: {result.decision.value}",
        extra={
            "signal_id": result.signal_id,
            "decision": result.decision.value,
            "reason": result.reason,
        },
    )
    
    # Build response
    response_data = {
        "accepted": result.decision == SignalDecision.ACCEPTED,
        "decision": result.decision.value,
        "reason": result.reason,
    }
    
    if result.decision == SignalDecision.ACCEPTED:
        response_data.update({
            "leverage": result.leverage,
            "position_side": result.position_side,
            "signal_id": result.signal_id,
            "queue_name": result.queue_name,
        })
    
    status_code = status.HTTP_200_OK if result.decision == SignalDecision.ACCEPTED else status.HTTP_202_ACCEPTED
    return JSONResponse(status_code=status_code, content=response_data)


@app.get("/api/v1/bots/health")
async def get_bots_health():
    """Get health status of connected bots."""
    if signal_handler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not initialized",
        )
    
    unhealthy_bots = await signal_handler.circuit_breaker.get_unhealthy_bots()
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "unhealthy_bots": unhealthy_bots,
        "total_unhealthy": len(unhealthy_bots),
    }


@app.post("/api/v1/bots/{bot_id}/heartbeat")
async def bot_heartbeat(bot_id: str):
    """Receive heartbeat from bot to update circuit breaker."""
    if signal_handler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service not initialized",
        )
    
    await signal_handler.circuit_breaker.record_heartbeat(bot_id)
    
    return {
        "status": "ok",
        "bot_id": bot_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
