from typing import Dict, Any
from fastapi import APIRouter, Depends, Body, HTTPException
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
    orcid_db = db.dict("orcid_status")
    new_orcid_id = payload.get("orcid_id")
    is_enabled = payload.get("is_enabled", False)

    orcid_client = Orcid(settings)
    fresh_data = await orcid_client.fetch_profile(new_orcid_id)
    
    if not fresh_data:
        raise HTTPException(status_code=400, detail="Invalid ORCID ID or service unreachable.")

    history = fresh_data.get("history", {})
    last_modified = history.get("last-modified-date", {}).get("value") if history else None

    new_status = OrcidStatus(
        user_id=user_id,
        orcid_id=new_orcid_id,
        is_enabled=is_enabled,
        payload=fresh_data,
        orcid_last_modified=last_modified,
        local_last_checked=datetime.now(timezone.utc)
    )
    
    orcid_db[user_id] = new_status.model_dump(mode='json')
    return {"message": "ORCID settings saved and profile synced.", "status": "success"}

@router.get("/profile", response_model=OrcidProfileResponse)
async def get_orcid_profile(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> OrcidProfileResponse:
    orcid_db = db.dict("orcid_status")
    status_data = orcid_db.get(user_id)
    if not status_data:
        raise HTTPException(status_code=404, detail="Profile not synced.")

    status = OrcidStatus(**status_data)
    
    if not status.is_enabled:
        raise HTTPException(status_code=403, detail="Integration disabled.")

    orcid_client = Orcid(settings)
    profile = orcid_client.parse_profile(status.payload, status)
    profile.sync_status = "cached"
    return profile

@router.post("/sync", response_model=OrcidProfileResponse)
async def sync_orcid_profile(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> OrcidProfileResponse:
    orcid_db = db.dict("orcid_status")
    status_data = orcid_db.get(user_id)
    if not status_data:
        raise HTTPException(status_code=404, detail="ORCID not linked.")

    status = OrcidStatus(**status_data)
    orcid_client = Orcid(settings)
    fresh_data = await orcid_client.fetch_profile(status.orcid_id)
    
    if fresh_data:
        history = fresh_data.get("history", {})
        status.payload = fresh_data
        status.orcid_last_modified = history.get("last-modified-date", {}).get("value") if history else None
        status.local_last_checked = datetime.now(timezone.utc)
        orcid_db[user_id] = status.model_dump(mode='json')

    profile = orcid_client.parse_profile(status.payload, status)
    profile.sync_status = "updated"
    return profile