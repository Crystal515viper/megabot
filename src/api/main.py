"""FastAPI application for Trading System API Gateway."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
import logging
import json

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from loguru import logger
import redis.asyncio as redis

from src.db.session import init_db_pool, close_db_pool
from src.api.routers import status, trades, metrics, stream
from src.api.tasks import schedule_daily_metrics, schedule_weekly_cleanup


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}',
)
log = logging.getLogger(__name__)


# Rate limiter setup
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown events."""
    # Startup
    log.info("Starting API Gateway...")
    
    # Initialize database pool
    await init_db_pool()
    log.info("Database pool initialized")
    
    # Start background tasks
    background_tasks = [
        asyncio.create_task(schedule_daily_metrics()),
        asyncio.create_task(schedule_weekly_cleanup()),
    ]
    log.info("Background tasks started")
    
    yield
    
    # Shutdown
    log.info("Shutting down API Gateway...")
    
    # Cancel background tasks
    for task in background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    # Close database pool
    await close_db_pool()
    log.info("Database pool closed")


# Create FastAPI app
app = FastAPI(
    title="Trading System API",
    description="Unified REST API + SSE for trading dashboard and Telegram bot",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests with timing."""
    start_time = datetime.utcnow()
    
    response = await call_next(request)
    
    duration = (datetime.utcnow() - start_time).total_seconds()
    
    log.info(
        json.dumps({
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 2),
            "client_ip": request.client.host if request.client else "unknown",
        })
    )
    
    return response


# Include routers
app.include_router(status.router, prefix="/api/v1")
app.include_router(trades.router, prefix="/api/v1")
app.include_router(metrics.router, prefix="/api/v1")
app.include_router(stream.router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """
    Basic health check endpoint.
    Returns 200 OK if the service is running.
    """
    return {"status": "healthy", "timestamp": datetime.utcnow()}


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Trading System API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# Event handler for trade closure (cache invalidation)
async def on_trade_closed(redis_client: redis.Redis, trade_id: int):
    """
    Called when a trade is closed to invalidate metrics cache.
    
    This should be triggered by the bots or orchestrator
    when a position status changes to CLOSED/STOPPED/LIQUIDATED.
    """
    from src.api.aggregators import MetricsAggregator
    
    aggregator = MetricsAggregator(redis_client)
    await aggregator.invalidate_cache()
    
    log.info(f"Metrics cache invalidated after trade {trade_id} closed")


# Example of how to trigger cache invalidation from external services
@app.post("/api/v1/events/trade_closed")
async def trade_closed_event(
    trade_id: int,
    redis_client: redis.Redis = None,
):
    """
    Webhook endpoint for trade closure events.
    
    Called by bots when a position is closed to trigger
    immediate cache invalidation.
    """
    if redis_client is None:
        redis_client = redis.from_url("redis://localhost:6379/0")
    
    await on_trade_closed(redis_client, trade_id)
    
    return {"status": "ok", "message": f"Trade {trade_id} closure processed"}


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
