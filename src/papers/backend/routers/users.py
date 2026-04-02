import os
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel, ValidationError
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db, get_settings
from papers.backend.config import Settings

from papers.backend.data_sources import _DATA_SOURCES
from papers.backend.models import OpenAlexUserStatus

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
    
@router.get("/me/sources/{source_id}/config")
async def get_user_source_config(
    source_id: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> Dict[str, Any]:
    """
    Retrieves the user's specific configuration values and system status for a given adapter.
    """
    source_id = source_id.lower().strip()
    if source_id not in _DATA_SOURCES:
        raise HTTPException(status_code=404, detail="Source adapter not found.")

    configs_db = db.dict("user_adapter_configs")
    user_configs = configs_db.get(user_id, {})
    current_config = user_configs.get(source_id, {})

    adapter_class = _DATA_SOURCES[source_id]
    adapter_state = adapter_class.get_config_state(user_id, db)
    current_config.update(adapter_state)

    return current_config


@router.put("/me/sources/{source_id}/config")
async def update_user_source_config(
    source_id: str,
    payload: Dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> dict:
    """
    Validates and updates the user's configuration for a specific adapter using its schema.
    """
    source_id = source_id.lower().strip()
    if source_id not in _DATA_SOURCES:
        raise HTTPException(status_code=404, detail="Source adapter not found.")

    adapter_class = _DATA_SOURCES[source_id]
    schema_class = adapter_class.config_schema

    try:
        validated_data = schema_class(**payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    configs_db = db.dict("user_adapter_configs")
    user_configs = configs_db.get(user_id, {})
    user_configs[source_id] = validated_data.model_dump(exclude_unset=True)
    configs_db[user_id] = user_configs

    adapter_class.apply_config_side_effects(user_id, validated_data, db)

    return {"detail": f"Configuration updated successfully for {source_id}."}