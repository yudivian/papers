"""
Dependency injection module for FastAPI route handlers.

This module provides reusable components for database connection pooling 
and request-scoped authentication resolution.
"""

from fastapi import Header, HTTPException, Depends
from beaver import BeaverDB

from papers.backend.config import Settings

def get_settings() -> Settings:
    """
    Provide a cached or newly instantiated Settings object.
    """
    return Settings.load_from_yaml()

def get_db(settings: Settings = Depends(get_settings)) -> BeaverDB:
    """
    Yields a BeaverDB instance for the current request lifecycle 
    using the dynamically injected configuration.
    """
    return BeaverDB(settings.database.file)

def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> str:
    """
    Extracts and validates the caller's identity from HTTP headers.
    Requires explicit user identity (no defaults).
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    return x_user_id