"""
Dependency injection module for FastAPI route handlers.

This module provides reusable components for database connection pooling 
and request-scoped authentication resolution.
"""

from fastapi import Header, HTTPException, Depends
from beaver import BeaverDB

from papers.backend.config import Settings

_global_db = None

def get_settings() -> Settings:
    """
    Provide a cached or newly instantiated Settings object.
    """
    return Settings.load_from_yaml()

def get_db() -> BeaverDB:
    """
    Yields a BeaverDB instance for the current request lifecycle 
    using the dynamically injected configuration.
    """
    global _global_db
    if _global_db is None:
        settings = get_settings()  # Llamada directa en lugar de inyección mágica
        _global_db = BeaverDB(settings.database.file)
    return _global_db

# def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> str:
#     """
#     Extracts and validates the caller's identity from HTTP headers.
#     Requires explicit user identity (no defaults).
#     """
#     if not x_user_id:
#         raise HTTPException(status_code=401, detail="Missing X-User-ID header")
#     return x_user_id

import jwt
from fastapi import Header, HTTPException, Depends
from papers.backend.config import Settings
# ... your existing imports ...

def get_current_user(
    x_user_id: str = Header(..., alias="X-User-ID"),
    settings: Settings = Depends(get_settings)
) -> str:
    """
    Retrieves the current user ID from the request header.
    Maintains the exact signature to avoid breaking any dependent routes.
    
    - Development mode: Trusts the plain text ID.
    - Production mode: Decodes and verifies the cryptographic signature (JWT).
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")

    # If in development, behavior is exactly as it was originally
    if settings.app.environment == "development":
        return x_user_id

    # If in production, treat the incoming string as a JWT
    try:
        payload = jwt.decode(
            x_user_id,
            settings.security.secret_key,
            algorithms=[settings.security.algorithm]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return user_id
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token signature")