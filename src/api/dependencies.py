"""API service dependencies."""
from fastapi import Depends, HTTPException, status
from slowapi import Limiter
from slowapi.util import get_remote_address

# Rate limiter instance for API routes
limiter = Limiter(key_func=get_remote_address)


def get_limiter() -> Limiter:
    """Get rate limiter instance."""
    return limiter

