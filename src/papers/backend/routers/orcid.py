from typing import Dict, Any
from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel
from beaver import BeaverDB
from datetime import datetime, timezone

from papers.backend.deps import get_current_user, get_db, get_settings
from papers.backend.config import Settings
from papers.backend.models import OrcidStatus, OrcidProfileResponse
from papers.backend.orcid import Orcid

router = APIRouter()

@router.get("/settings", response_model=Dict[str, Any])
async def get_orcid_settings(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> Dict[str, Any]:
    """
    Retrieves the current ORCID configuration for the authenticated user.
    Returns basic configuration data for frontend initialization.
    """
    # Access BeaverDB using the dictionary-like interface
    orcid_db = db.dict("orcid_status")
    status_data = orcid_db.get(user_id)
    
    if not status_data:
        return {"orcid_id": "", "is_enabled": False, "has_orcid": False}
        
    return {
        "orcid_id": status_data.get("orcid_id", ""),
        "is_enabled": status_data.get("is_enabled", False),
        "has_orcid": True
    }

@router.post("/settings", response_model=Dict[str, Any])
async def save_orcid_settings(
    payload: Dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> Dict[str, Any]:
    """
    Updates the user's ORCID configuration.
    If a new ORCID ID is provided, it triggers a fetch from the ORCID API
    to validate the ID and initialize the local cache.
    """
    new_orcid_id = payload.get("orcid_id", "").strip()
    is_enabled = payload.get("is_enabled", True)
    
    if not new_orcid_id:
        raise HTTPException(status_code=400, detail="ORCID ID is required.")

    orcid_db = db.dict("orcid_status")
    status_data = orcid_db.get(user_id)
    
    # If the user is setting an ORCID for the first time, or changing the ID
    if not status_data or status_data.get("orcid_id") != new_orcid_id:
        orcid_client = Orcid(settings)
        orcid_data = await orcid_client.fetch_profile(new_orcid_id)
        
        if not orcid_data:
            raise HTTPException(
                status_code=404, 
                detail="Could not retrieve the ORCID profile. Please verify the ID."
            )
            
        last_modified = None
        history = orcid_data.get("history", {})
        if history and history.get("last-modified-date"):
            last_modified = history["last-modified-date"].get("value")

        new_status = OrcidStatus(
            user_id=user_id,
            orcid_id=new_orcid_id,
            is_enabled=is_enabled,
            payload=orcid_data,
            orcid_last_modified=last_modified,
            local_last_checked=datetime.now(timezone.utc)
        )
        
        # Save state back to DB using synchronous dictionary assignment
        orcid_db[user_id] = new_status.model_dump(mode='json')
        
        return {"message": "ORCID linked and profile downloaded successfully.", "status": "new_linked"}
    
    # If the ID remains the same, just update the enabled/disabled toggle
    status_data["is_enabled"] = is_enabled
    orcid_db[user_id] = status_data
    
    return {"message": "ORCID configuration updated.", "status": "updated"}

@router.get("/profile", response_model=OrcidProfileResponse)
async def get_orcid_profile(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> OrcidProfileResponse:
    """
    Retrieves the enriched ORCID profile for the user.
    Performs a silent background sync with the ORCID API. If the public data
    is newer than the local cache, the cache is updated before returning.
    """
    orcid_db = db.dict("orcid_status")
    status_data = orcid_db.get(user_id)
    
    if not status_data:
        raise HTTPException(status_code=404, detail="No ORCID configured for this user.")
        
    orcid_status = OrcidStatus(**status_data)
    
    if not orcid_status.is_enabled:
        raise HTTPException(status_code=403, detail="ORCID integration is currently disabled.")

    orcid_client = Orcid(settings)
    sync_state = "up_to_date"
    
    # Fetch fresh profile for silent sync
    fresh_data = await orcid_client.fetch_profile(orcid_status.orcid_id)
    
    if fresh_data:
        history = fresh_data.get("history", {})
        new_modified_date = history.get("last-modified-date", {}).get("value") if history else None
        
        # Update payload if the remote data is newer
        if new_modified_date and (
            not orcid_status.orcid_last_modified or 
            new_modified_date > orcid_status.orcid_last_modified
        ):
            orcid_status.payload = fresh_data
            orcid_status.orcid_last_modified = new_modified_date
            sync_state = "updated"
            
        # Always update the local checked timestamp
        orcid_status.local_last_checked = datetime.now(timezone.utc)
        
        # Save state back to DB using synchronous dictionary assignment
        orcid_db[user_id] = orcid_status.model_dump(mode='json')
    else:
        # Network failure, fallback to cached data
        sync_state = "offline_fallback"

    # Parse payload into the frontend Pydantic model
    profile_response = orcid_client.parse_profile(orcid_status.payload, orcid_status)
    profile_response.sync_status = sync_state
    
    return profile_response