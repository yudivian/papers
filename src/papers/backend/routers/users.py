import os
from typing import List
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db, get_settings
from papers.backend.config import Settings

router = APIRouter()

class QuotaInfo(BaseModel):
    """
    Data Transfer Object providing a snapshot of user resource consumption.
    """
    used_bytes: int
    limit_bytes: int

class UserProfileResponse(BaseModel):
    """
    Standard response model for authenticated user identity and system metrics.
    """
    user_id: str
    active_data_sources: List[str]
    quota: QuotaInfo

@router.get("/me", response_model=UserProfileResponse)
async def get_user_profile(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> UserProfileResponse:
    """
    Retrieves the user profile and computes real-time disk usage.

    This method calculates the total physical footprint of the documents 
    registered in the global database by probing the filesystem directly, 
    matching it against the logical limits defined in the configuration.
    """
    docs_db = db.dict("global_documents")
    used_bytes = 0
    
    for doc_data in docs_db.values():
        storage_uri = doc_data.get("storage_uri", "")
        if os.path.exists(storage_uri):
            used_bytes += os.path.getsize(storage_uri)
            
    limit_bytes = settings.quotas.user_logical_limit_gb * (1024 ** 3)

    return UserProfileResponse(
        user_id=user_id,
        active_data_sources=settings.data_sources.priority,
        quota=QuotaInfo(used_bytes=used_bytes, limit_bytes=limit_bytes)
    )