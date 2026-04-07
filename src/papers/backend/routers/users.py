import os
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel, ValidationError
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db, get_settings
from papers.backend.config import Settings

from papers.backend.data_sources import _DATA_SOURCES
from papers.backend.data_sources import OpenAlexConfig, CoreConfig

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
    kb_count: int
    document_count: int

@router.get("/me", response_model=UserProfileResponse)
async def get_user_profile(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> UserProfileResponse:
    docs_db = db.dict("global_documents")
    kbs_db = db.dict("knowledge_bases")
    
    user_dois = set()
    kb_counter = 0 # Contador de KBs
    
    for kb in kbs_db.values():
        if kb.get("owner_id") == user_id:
            kb_counter += 1 # Incrementar por cada KB propia
            user_dois.update(kb.get("document_ids", []))
            
    # Calcular peso físico
    used_bytes = 0
    for doi in user_dois:
        doc_data = docs_db.get(doi)
        if doc_data:
            storage_uri = doc_data.get("storage_uri", "")
            if os.path.exists(storage_uri):
                used_bytes += os.path.getsize(storage_uri)
            
    limit_bytes = settings.quotas.user_logical_limit_gb * (1024 ** 3)

    return UserProfileResponse(
        user_id=user_id,
        active_data_sources=settings.data_sources.priority,
        quota=QuotaInfo(used_bytes=used_bytes, limit_bytes=limit_bytes),
        # DEVOLVER LOS NUEVOS DATOS:
        kb_count=kb_counter,
        document_count=len(user_dois)
    )
    
@router.get("/me/sources/{source_id}/config")
async def get_user_source_config(
    source_id: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings) # <-- Inyectamos settings
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
    
    # Pasamos settings genéricamente. El adaptador sabrá qué hacer con ellos.
    adapter_state = adapter_class.get_config_state(user_id, db, settings)
    
    # Mantenemos la estructura plana pero guardamos una copia en "state"
    # para que ui.js pueda hacer res.state.daily_system_search_count
    current_config.update(adapter_state)
    current_config["state"] = adapter_state

    return current_config

@router.put("/me/sources/{source_id}/config")
async def update_user_source_config(
    source_id: str,
    config_data: Dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
):
    """
    Updates the user-specific configuration for a given data source adapter.
    """
    source_id = source_id.lower().strip()
    if source_id not in _DATA_SOURCES:
        raise HTTPException(status_code=404, detail="Source adapter not found.")

    configs_db = db.dict("user_adapter_configs")
    user_configs = configs_db.get(user_id, {})

    # Guardamos la configuración (incluyendo el nuevo booleano use_personal_key)
    user_configs[source_id] = config_data
    configs_db[user_id] = user_configs

    # Ejecutamos efectos secundarios (como resetear el estado de salud de la llave)
    adapter_class = _DATA_SOURCES[source_id]
    
    # Intentamos validar con el modelo específico si es OpenAlex
    config_schema = getattr(adapter_class, "config_schema", None)
    
    if config_schema:
        try:
            validated_config = config_schema(**config_data)
            adapter_class.apply_config_side_effects(user_id, validated_config, db)
        except ValidationError as e:
             raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success", "message": "Configuration updated"}