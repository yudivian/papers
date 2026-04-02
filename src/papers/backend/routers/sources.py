"""
API router for Data Sources Discovery and Schema retrieval.
"""
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException

from papers.backend.data_sources import _DATA_SOURCES

router = APIRouter()

@router.get("", response_model=List[Dict[str, str]])
async def list_available_sources() -> List[Dict[str, str]]:
    """
    Lists all registered data source adapters within the system ecosystem.
    """
    sources = []
    for source_id in _DATA_SOURCES.keys():
        sources.append({
            "id": source_id,
            "name": source_id.capitalize()
        })
    return sources

@router.get("/{source_id}/schema", response_model=Dict[str, Any])
async def get_source_schema(source_id: str) -> Dict[str, Any]:
    """
    Retrieves the dynamic UI schema for a specific data source adapter.
    """
    source_id = source_id.lower().strip()
    
    if source_id not in _DATA_SOURCES:
        raise HTTPException(
            status_code=404,
            detail=f"Source adapter '{source_id}' not found."
        )
        
    adapter_class = _DATA_SOURCES[source_id]
    return adapter_class.get_ui_schema()