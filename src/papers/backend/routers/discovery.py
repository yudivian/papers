from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db, get_settings
from papers.backend.models import GlobalDocumentMeta
from papers.backend.config import Settings
from papers.backend.orchestrator import DiscoveryOrchestrator

router = APIRouter()

@router.get("/doi/{doi:path}", response_model=GlobalDocumentMeta)
async def resolve_doi(
    doi: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> GlobalDocumentMeta:
    """
    Resolves comprehensive metadata for a DOI via the DiscoveryOrchestrator.

    This endpoint delegates the tiered resolution strategy to the orchestrator 
    and handles the high-level HTTP 404 response if the document cannot be 
    found in any configured provider.
    """
    orchestrator = DiscoveryOrchestrator(settings=settings, db=db, user_id=user_id)
    meta = await orchestrator.resolve_doi(doi)
    
    if not meta:
        raise HTTPException(
            status_code=404, 
            detail=f"Metadata for DOI '{doi}' could not be resolved."
        )
    return meta

@router.get("/search", response_model=Dict[str, List[GlobalDocumentMeta]])
async def semantic_search(
    q: str = Query(..., description="Natural language semantic query string"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results per source"),
    source: Optional[str] = Query(None, description="Specific provider to target"),
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> Dict[str, List[GlobalDocumentMeta]]:
    """
    Performs a classified semantic search across all prioritized data sources.

    The response is organized as a dictionary where each key corresponds to 
    the name of the provider that returned the results.
    """
    orchestrator = DiscoveryOrchestrator(settings=settings, db=db, user_id=user_id)
    return await orchestrator.search(query=q, limit=limit, target_source=source)