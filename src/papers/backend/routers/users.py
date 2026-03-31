"""
API router for user identity and system quota management.

This module provides endpoints for retrieving the authenticated user's 
profile, active configuration settings, and real-time storage utilization metrics.
"""

import os
from typing import List
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db
from papers.backend.config import Settings

router = APIRouter()
settings = Settings.load_from_yaml()

class QuotaInfo(BaseModel):
    """
    Data Transfer Object representing the user's storage consumption.
    """
    used_bytes: int
    limit_bytes: int

class UserProfileResponse(BaseModel):
    """
    Data Transfer Object representing the user's identity and system status.
    """
    user_id: str
    active_data_sources: List[str]
    quota: QuotaInfo

@router.get("/me", response_model=UserProfileResponse)
async def get_user_profile(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> UserProfileResponse:
    """
    Retrieves the authenticated user's profile and calculates current disk usage.

    Iterates through the global document registry to dynamically compute 
    the exact physical footprint of the user's library on the server's disk.

    Args:
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        UserProfileResponse: The user's profile, active data sources, and real-time quota metrics.
    """
    docs_db = db.dict("global_documents")
    used_bytes = 0
    
    for doc_data in docs_db.values():
        storage_uri = doc_data.get("storage_uri", "")
        if os.path.exists(storage_uri):
            used_bytes += os.path.getsize(storage_uri)
            
    limit_bytes = 5 * 1024 * 1024 * 1024 

    return UserProfileResponse(
        user_id=user_id,
        active_data_sources=settings.data_sources.priority,
        quota=QuotaInfo(
            used_bytes=used_bytes,
            limit_bytes=limit_bytes
        )
    )