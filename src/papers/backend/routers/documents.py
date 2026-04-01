"""
API router for global document management and physical asset serving.

This module provides endpoints for cataloging the ingested library, 
streaming format-agnostic physical files to the client, and executing 
rule-based cleanup operations to maintain storage quotas and referential 
integrity within the BeaverDB databases.
"""
import os
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db
from papers.backend.models import GlobalDocumentMeta

router = APIRouter()

class CleanupRequest(BaseModel):
    """
    Data Transfer Object defining the filtering criteria for mass deletion.
    """
    before_date: Optional[datetime] = None
    unlinked_only: bool = False
    specific_dois: Optional[List[str]] = None

class CleanupResponse(BaseModel):
    """
    Data Transfer Object summarizing the result of a cleanup operation.
    """
    deleted_count: int
    freed_bytes: int

@router.get("", response_model=List[GlobalDocumentMeta])
async def list_documents(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> List[GlobalDocumentMeta]:
    """
    Retrieves the complete catalog of all documents ingested by the system.

    Args:
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        List[GlobalDocumentMeta]: A list containing the metadata for every stored document.
    """
    docs_db = db.dict("global_documents")
    return [GlobalDocumentMeta.model_validate(data) for data in docs_db.values()]

@router.get("/{doi:path}/file", response_class=FileResponse)
async def get_document_file(
    doi: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> FileResponse:
    """
    Streams the physical binary file to the client for rendering or downloading.

    This endpoint dynamically reads the registered MIME type from the metadata, 
    ensuring the system remains completely agnostic to the file format (PDF, EPUB, XML).

    Args:
        doi: The target Digital Object Identifier.
        user_id: The authenticated user's identifier.
        db: The active BeaverDB connection instance.

    Returns:
        FileResponse: The physical file with the exact media type headers required by the browser.

    Raises:
        HTTPException: A 404 error if the metadata is missing or the file is not on disk.
    """
    docs_db = db.dict("global_documents")
    
    if doi not in docs_db:
        raise HTTPException(status_code=404, detail="Document metadata not found.")
        
    doc_data = docs_db[doi]
    storage_uri = doc_data.get("storage_uri", "")
    
    if not os.path.exists(storage_uri):
        raise HTTPException(status_code=404, detail="Physical file not found on disk.")
        
    return FileResponse(
        path=storage_uri, 
        media_type=doc_data.get("mime_type", "application/octet-stream"),
        filename=os.path.basename(storage_uri)
    )

@router.delete("/{doi:path}")
async def delete_document(
    doi: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> dict:
    """
    Permanently removes a single document and purges all related references.

    This operation enforces strict referential integrity by traversing all 
    Knowledge Bases to remove pointers, deleting the physical file from 
    the configured storage adapter, and dropping the semantic vector.

    Args:
        doi: The target Digital Object Identifier to delete.
        user_id: The authenticated user's identifier.
        db: The active BeaverDB connection instance.

    Returns:
        dict: A success confirmation message.

    Raises:
        HTTPException: A 404 error if the document does not exist.
    """
    docs_db = db.dict("global_documents")
    if doi not in docs_db:
        raise HTTPException(status_code=404, detail="Document not found.")

    kbs_db = db.dict("knowledge_bases")
    for kb_id, kb_data in kbs_db.items():
        doc_ids = kb_data.get("document_ids", [])
        if doi in doc_ids:
            doc_ids.remove(doi)
            kb_data["document_ids"] = doc_ids
            kbs_db[kb_id] = kb_data

    storage_uri = docs_db[doi].get("storage_uri", "")
    if os.path.exists(storage_uri):
        os.remove(storage_uri)

    vectors_db = db.dict("semantic_vectors")
    if doi in vectors_db:
        del vectors_db[doi]

    del docs_db[doi]

    return {"detail": "Document permanently deleted."}

@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_documents(
    payload: CleanupRequest,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> CleanupResponse:
    """
    Executes a bulk deletion of documents based on complex filtering criteria.

    This operation safely reclaims physical storage space by sweeping all 
    Knowledge Bases, removing pointers to the deleted documents, and subsequently 
    purging the physical files and semantic vectors based on the unlinked status 
    or date thresholds.

    Args:
        payload: The filtering rules (date thresholds, linkage status, specific DOIs).
        user_id: The authenticated user's identifier.
        db: The active BeaverDB connection instance.

    Returns:
        CleanupResponse: A summary containing the number of deleted documents 
                         and the total bytes freed from the storage disk.
    """
    docs_db = db.dict("global_documents")
    kbs_db = db.dict("knowledge_bases")
    vectors_db = db.dict("semantic_vectors")

    linked_dois = set()
    for kb_data in kbs_db.values():
        linked_dois.update(kb_data.get("document_ids", []))

    dois_to_delete = set()
    for doi, doc_data in docs_db.items():
        if payload.unlinked_only and doi in linked_dois:
            continue

        if payload.specific_dois is not None and doi not in payload.specific_dois:
            continue

        if payload.before_date:
            storage_uri = doc_data.get("storage_uri", "")
            if os.path.exists(storage_uri):
                mtime = datetime.fromtimestamp(os.path.getmtime(storage_uri), tz=timezone.utc)
                if mtime > payload.before_date:
                    continue

        dois_to_delete.add(doi)

    freed_bytes = 0
    for doi in dois_to_delete:
        if not payload.unlinked_only:
            for kb_id, kb_data in kbs_db.items():
                doc_ids = kb_data.get("document_ids", [])
                if doi in doc_ids:
                    doc_ids.remove(doi)
                    kb_data["document_ids"] = doc_ids
                    kbs_db[kb_id] = kb_data

        doc_data = docs_db[doi]
        storage_uri = doc_data.get("storage_uri", "")
        if os.path.exists(storage_uri):
            freed_bytes += os.path.getsize(storage_uri)
            os.remove(storage_uri)

        if doi in vectors_db:
            del vectors_db[doi]

        del docs_db[doi]

    return CleanupResponse(
        deleted_count=len(dois_to_delete),
        freed_bytes=freed_bytes
    )