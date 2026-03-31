"""
Dependency injection module for FastAPI route handlers.

This module provides reusable components for database connection pooling 
and request-scoped authentication resolution.
"""

from fastapi import Header, HTTPException
from beaver import BeaverDB

from papers.backend.config import Settings

_settings = Settings.load_from_yaml()
_db_instance = BeaverDB(_settings.database.file)

def get_db() -> BeaverDB:
    """
    Yields a singleton BeaverDB instance for the current request lifecycle.
    """
    return _db_instance

def get_current_user(x_user_id: str = Header(default="default_user")) -> str:
    """
    Extracts and validates the caller's identity from HTTP headers.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-ID header")
    return x_user_id