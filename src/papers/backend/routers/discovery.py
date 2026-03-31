"""
API router for document discovery and semantic search operations.

This module exposes endpoints for resolving metadata via Digital Object 
Identifiers (DOIs) and performing natural language semantic searches against 
the local vector database. It implements a fallback resolution strategy, 
querying the local cache before reaching out to external satellite providers.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db
from papers.backend.models import GlobalDocumentMeta
from papers.backend.data_sources import get_data_source
from papers.backend.config import Settings

router = APIRouter()
settings = Settings.load_from_yaml()

@router.get("/doi/{doi:path}", response_model=GlobalDocumentMeta)
async def resolve_doi(
    doi: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> GlobalDocumentMeta:
    """
    Resolves comprehensive metadata for a specific document identifier.

    This endpoint attempts to fulfill the request using the local cache first 
    to preserve external API quotas. If a cache miss occurs, it seamlessly 
    falls back to the OpenAlex satellite provider.

    Args:
        doi: The target Digital Object Identifier, URL-encoded if necessary.
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        GlobalDocumentMeta: The normalized document metadata payload.

    Raises:
        HTTPException: A 404 error if the DOI cannot be resolved across all providers.
    """
    cache_source = get_data_source(
        "cache", 
        db_path=settings.database.file
    )
    
    cached_meta = await cache_source.fetch_by_doi(doi)
    if cached_meta:
        return cached_meta

    openalex_source = get_data_source(
        "openalex",
        user_id=user_id,
        db=db,
        config=settings.data_sources.openalex,
        db_path=settings.database.file
    )
    
    external_meta = await openalex_source.fetch_by_doi(doi)
    if external_meta:
        return external_meta

    raise HTTPException(
        status_code=404, 
        detail=f"Metadata for DOI '{doi}' could not be resolved locally or externally."
    )

@router.get("/search", response_model=List[GlobalDocumentMeta])
async def semantic_search(
    q: str = Query(..., description="Natural language semantic query string"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of results to return"),
    user_id: str = Depends(get_current_user)
) -> List[GlobalDocumentMeta]:
    """
    Executes a localized semantic vector search against ingested documents.

    This endpoint converts the incoming textual query into a high-dimensional 
    vector representation and computes cosine similarity against all locally 
    stored document vectors.

    Args:
        q: The user's natural language search prompt.
        limit: The threshold for the maximum number of matches to return.
        user_id: The authenticated user's identifier, injected via dependencies.

    Returns:
        List[GlobalDocumentMeta]: A ranked array of the most semantically relevant 
                                  documents, ordered by descending similarity score.
    """
    cache_source = get_data_source(
        "cache", 
        db_path=settings.database.file
    )
    
    results = await cache_source.search_by_text(query=q, limit=limit)
    return results