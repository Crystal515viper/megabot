"""Main entry point for the orchestrator service."""

from fastapi import FastAPI
from loguru import logger
import sys

# Configure logging
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
)

app = FastAPI(
    title="Trading Orchestrator",
    description="Main orchestrator service for trading system",
    version="1.0.0",
)


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("Starting Orchestrator service...")
    # TODO: Initialize database connections
    # TODO: Initialize Redis connections
    # TODO: Load configuration
    logger.info("Orchestrator service started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup services on shutdown."""
    logger.info("Shutting down Orchestrator service...")
    # TODO: Close database connections
    # TODO: Close Redis connections
    logger.info("Orchestrator service stopped")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "orchestrator",
        "version": "1.0.0",
        "status": "running",
    }
