"""
API router for global document management and physical file operations.

This module exposes endpoints for retrieving the library catalog, streaming 
format-agnostic physical files, and executing cleanup routines. It delegates 
all physical I/O constraints to the injected storage adapters, avoiding 
direct host operating system bindings.
"""
import os
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db, get_settings
from papers.backend.models import GlobalDocumentMeta
from papers.backend.config import Settings
from papers.backend.storages import get_storage

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
    """
    docs_db = db.dict("global_documents")
    return [GlobalDocumentMeta.model_validate(data) for data in docs_db.values()]

@router.get("/{doi:path}/file", response_class=Response)
async def get_document_file(
    doi: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> Response:
    """
    Streams the physical binary file to the client dynamically.
    """
    docs_db = db.dict("global_documents")
    
    if doi not in docs_db:
        raise HTTPException(status_code=404, detail="Document metadata not found.")
        
    doc_data = docs_db[doi]
    storage_uri = doc_data.get("storage_uri", "")
    
    storage = get_storage(settings.storage.selected, base_path=settings.storage.local.base_path)
    
    if not await storage.exists(storage_uri):
        raise HTTPException(status_code=404, detail="Physical file not found in storage.")
        
    filename = os.path.basename(storage_uri)
    media_type = doc_data.get("mime_type", "application/octet-stream")
    
    return await storage.serve(storage_uri, media_type, filename)

@router.delete("/{doi:path}")
async def delete_document(
    doi: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> dict:
    """
    Permanently removes a single document and purges all related references.
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
    storage = get_storage(settings.storage.selected, base_path=settings.storage.local.base_path)
    
    if await storage.exists(storage_uri):
        await storage.delete(storage_uri)

    vectors_db = db.dict("semantic_vectors")
    if doi in vectors_db:
        del vectors_db[doi]

    del docs_db[doi]

    return {"detail": "Document permanently deleted."}

@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_documents(
    payload: CleanupRequest,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> CleanupResponse:
    """
    Executes a bulk deletion of documents based on complex filtering criteria.
    """
    docs_db = db.dict("global_documents")
    kbs_db = db.dict("knowledge_bases")
    vectors_db = db.dict("semantic_vectors")
    
    storage = get_storage(settings.storage.selected, base_path=settings.storage.local.base_path)

    linked_dois = set()
    for kb_data in kbs_db.values():
        linked_dois.update(kb_data.get("document_ids", []))

    dois_to_delete = set()
    for doi, doc_data in docs_db.items():
        if payload.unlinked_only and doi in linked_dois:
            continue

        if payload.specific_dois is not None and doi not in payload.specific_dois:
            continue

        # DENTRO DEL BUCLE DE LIMPIEZA: for doi, doc_data in docs_db.items():
        if payload.before_date:
            doc_date = None
            
            # 1. Intentar leer desde la Base de Datos (Ruta rápida)
            ingested_str = doc_data.get("ingested_at")
            if ingested_str:
                # Convertir el string ISO de la BD a objeto datetime
                # (Aseguramos compatibilidad con el formato UTC)
                if isinstance(ingested_str, str):
                    doc_date = datetime.fromisoformat(ingested_str.replace("Z", "+00:00"))
                else:
                    doc_date = ingested_str
            
            # 2. Fallback para documentos Legacy (Ruta lenta + Auto-Sanación)
            else:
                storage_uri = doc_data.get("storage_uri", "")
                if await storage.exists(storage_uri):
                    doc_date = await storage.get_modified_time(storage_uri)
                    
                    # ¡AUTO-SANACIÓN! Guardamos la fecha para no volver al disco la próxima vez
                    doc_data["ingested_at"] = doc_date.isoformat()
                    docs_db[doi] = doc_data 
                else:
                    # Si no hay fecha en BD y el archivo físico no existe, 
                    # forzamos su eliminación para limpiar la basura
                    pass 

            # 3. Comparación (Si es más nuevo que el límite, lo saltamos)
            if doc_date and doc_date > payload.before_date:
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
        
        if await storage.exists(storage_uri):
            freed_bytes += await storage.get_size(storage_uri)
            await storage.delete(storage_uri)

        if doi in vectors_db:
            del vectors_db[doi]

        del docs_db[doi]

    return CleanupResponse(
        deleted_count=len(dois_to_delete),
        freed_bytes=freed_bytes
    )