"""
API router for Knowledge Base (workspace) management.

This module provides the necessary endpoints to create, retrieve, delete, 
and reorganize logical document groupings. It enforces data isolation by 
scoping all operations to the authenticated user's identifier.
"""

import uuid
from datetime import datetime 
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db
from papers.backend.models import GlobalDocumentMeta, KnowledgeBase

router = APIRouter()

class KBCreateRequest(BaseModel):
    """
    Data Transfer Object for creating a new Knowledge Base.
    """
    name: str
    description: Optional[str] = ""

class KBResponse(BaseModel):
    """
    Data Transfer Object representing a Knowledge Base entity.
    """
    kb_id: str
    owner_id: str
    name: str
    description: str
    document_ids: List[str]
    created_at: Optional[datetime] = None 

class KBDetailResponse(BaseModel):
    """
    Data Transfer Object for retrieving a Knowledge Base with its hydrated documents.
    """
    kb_id: str
    name: str
    description: str
    documents: List[GlobalDocumentMeta]

class KBTransferRequest(BaseModel):
    """
    Data Transfer Object for moving documents between Knowledge Bases.
    """
    dois: List[str]
    source_kb_id: str

class KBTransferResponse(BaseModel):
    """
    Data Transfer Object summarizing a successful document transfer.
    """
    transferred_count: int
    
class KBUpdateRequest(BaseModel):
    """Schema for updating an existing Knowledge Base."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    
class AddDocumentsRequest(BaseModel):
    dois: List[str]


@router.get("", response_model=List[KBResponse])
async def list_knowledge_bases(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> List[KBResponse]:
    """
    Retrieves all Knowledge Bases owned by the authenticated user.

    Args:
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        List[KBResponse]: A list of all workspaces associated with the user.
    """
    kbs_db = db.dict("knowledge_bases")
    user_kbs = []
    
    for kb_data in kbs_db.values():
        if kb_data.get("owner_id") == user_id:
            user_kbs.append(KBResponse.model_validate(kb_data))
            
    return user_kbs

@router.post("", response_model=KBResponse, status_code=201)
async def create_knowledge_base(
    payload: KBCreateRequest,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> KBResponse:
    """
    Provisions a new, empty Knowledge Base for the authenticated user.
    """
    kbs_db = db.dict("knowledge_bases")
    kb_id = f"kb_{uuid.uuid4().hex}"
    
    # 1. Usamos el modelo real de Pydantic para que genere la fecha automáticamente
    kb_obj = KnowledgeBase(
        kb_id=kb_id,
        owner_id=user_id,
        name=payload.name,
        description=payload.description or "",
        document_ids=[]
    )
    
    # 2. Lo convertimos a diccionario (json) para guardarlo en BeaverDB
    new_kb_dict = kb_obj.model_dump(mode="json")
    
    # 3. Guardamos y retornamos
    kbs_db[kb_id] = new_kb_dict
    return KBResponse.model_validate(new_kb_dict)

@router.get("/{kb_id}", response_model=KBDetailResponse)
async def get_knowledge_base(
    kb_id: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> KBDetailResponse:
    """
    Retrieves a specific Knowledge Base and hydrates its document references.

    Args:
        kb_id: The target Knowledge Base identifier.
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        KBDetailResponse: The workspace details bundled with full document metadata.

    Raises:
        HTTPException: A 404 error if the KB does not exist.
        HTTPException: A 403 error if the user does not own the requested KB.
    """
    kbs_db = db.dict("knowledge_bases")
    docs_db = db.dict("global_documents")
    
    kb_data = kbs_db.get(kb_id)
    if not kb_data:
        raise HTTPException(status_code=404, detail="Knowledge Base not found.")
        
    if kb_data.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied to this Knowledge Base.")

    hydrated_docs = []
    for doi in kb_data.get("document_ids", []):
        if doi in docs_db:
            hydrated_docs.append(GlobalDocumentMeta.model_validate(docs_db[doi]))

    return KBDetailResponse(
        kb_id=kb_data["kb_id"],
        name=kb_data["name"],
        description=kb_data["description"],
        documents=hydrated_docs
    )

@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> dict:
    """
    Permanently deletes a Knowledge Base entity.

    Note: This operation only removes the logical workspace grouping. It does 
    not trigger the deletion of the underlying physical documents or vectors.

    Args:
        kb_id: The target Knowledge Base identifier.
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        dict: A success confirmation message.

    Raises:
        HTTPException: A 404 error if the KB does not exist.
        HTTPException: A 403 error if the user does not own the requested KB.
    """
    kbs_db = db.dict("knowledge_bases")
    
    kb_data = kbs_db.get(kb_id)
    if not kb_data:
        raise HTTPException(status_code=404, detail="Knowledge Base not found.")
        
    if kb_data.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied to this Knowledge Base.")

    del kbs_db[kb_id]
    return {"detail": "Knowledge Base deleted successfully."}

@router.post("/{kb_id}/transfer", response_model=KBTransferResponse)
async def transfer_documents(
    kb_id: str,
    payload: KBTransferRequest,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> KBTransferResponse:
    """
    Executes a transactional transfer of documents between two Knowledge Bases.

    Args:
        kb_id: The destination Knowledge Base identifier (from the URL path).
        payload: The source KB identifier and the list of DOIs to move.
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        KBTransferResponse: A summary of the successfully transferred documents.

    Raises:
        HTTPException: A 404 error if either the source or destination KB is missing.
        HTTPException: A 403 error if the user does not own both KBs.
    """
    kbs_db = db.dict("knowledge_bases")
    
    dest_kb = kbs_db.get(kb_id)
    source_kb = kbs_db.get(payload.source_kb_id)
    
    if not dest_kb or not source_kb:
        raise HTTPException(status_code=404, detail="Source or destination Knowledge Base not found.")
        
    if dest_kb.get("owner_id") != user_id or source_kb.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied during transfer operation.")

    source_docs = set(source_kb.get("document_ids", []))
    dest_docs = set(dest_kb.get("document_ids", [])) 
    
    transferred = 0
    for doi in payload.dois:
        if doi in source_docs:
            source_docs.remove(doi)  
            dest_docs.add(doi)      
            transferred += 1

    source_kb["document_ids"] = list(source_docs)
    dest_kb["document_ids"] = list(dest_docs)
    
    kbs_db[payload.source_kb_id] = source_kb
    kbs_db[kb_id] = dest_kb

    return KBTransferResponse(transferred_count=transferred)

@router.patch("/{kb_id}", response_model=KBResponse)
async def update_knowledge_base(
    kb_id: str,
    payload: KBUpdateRequest,
    current_user = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> KBResponse:
    """Updates the name and/or description of an existing Knowledge Base."""
    kbs_db = db.dict("knowledge_bases")
    kb_data = kbs_db.get(kb_id)
    
    user_id = current_user.user_id if hasattr(current_user, 'user_id') else current_user

    if not kb_data or kb_data.get("owner_id") != user_id:
        raise HTTPException(status_code=404, detail="Knowledge Base not found or access denied.")

    if payload.name is not None:
        kb_data["name"] = payload.name
    if payload.description is not None:
        kb_data["description"] = payload.description

    kbs_db[kb_id] = kb_data
    return KBResponse.model_validate(kb_data)


@router.post("/{kb_id}/copy", response_model=KBTransferResponse)
async def copy_documents(
    kb_id: str,
    payload: KBTransferRequest,
    current_user = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> KBTransferResponse:
    """Copy documents from one KB to another without deleting them from the source."""
    kbs_db = db.dict("knowledge_bases")
    dest_kb = kbs_db.get(kb_id)
    source_kb = kbs_db.get(payload.source_kb_id)
    
    user_id = current_user.user_id if hasattr(current_user, 'user_id') else current_user

    if not dest_kb or dest_kb.get("owner_id") != user_id:
        raise HTTPException(status_code=404, detail="Target Knowledge Base not found.")
    
    if not source_kb or source_kb.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied to source KB.")

    source_docs = set(source_kb.get("document_ids", []))
    dest_docs = set(dest_kb.get("document_ids", [])) 
    
    copied = 0
    for doi in payload.dois:
        if doi in source_docs:
            dest_docs.add(doi)
            copied += 1

    dest_kb["document_ids"] = list(dest_docs)
    kbs_db[kb_id] = dest_kb

    return KBTransferResponse(transferred_count=copied)


@router.delete("/{kb_id}/documents/{doi:path}")
async def unlink_document_from_kb(
    kb_id: str,
    doi: str,
    current_user = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
):
    """Removes the reference to a document in a specific KB."""
    kbs_db = db.dict("knowledge_bases")
    kb_data = kbs_db.get(kb_id)
    
    user_id = current_user.user_id if hasattr(current_user, 'user_id') else current_user

    if not kb_data or kb_data.get("owner_id") != user_id:
        raise HTTPException(status_code=404, detail="Knowledge Base not found.")

    doc_ids = kb_data.get("document_ids", [])
    if doi in doc_ids:
        doc_ids.remove(doi)
        kb_data["document_ids"] = doc_ids
        kbs_db[kb_id] = kb_data
        
    return {"status": "unlinked"}

# En src/papers/backend/routers/kbs.py


@router.post("/{kb_id}/documents", status_code=200)
async def add_documents_to_kb(
    kb_id: str,
    payload: AddDocumentsRequest,
    db: BeaverDB = Depends(get_db)
):
    """
    Links documents that already exist in cache
    to a specific Knowledge Base.
    """
    kbs_db = db.dict("knowledge_bases")
    if kb_id not in kbs_db:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    
    kb_data = kbs_db[kb_id]
    current_docs = set(kb_data.get("document_ids", []))
    
    new_dois = [doi for doi in payload.dois if doi not in current_docs]
    
    if new_dois:
        kb_data["document_ids"] = list(current_docs.union(new_dois))
        kbs_db[kb_id] = kb_data
        
    return {"added_count": len(new_dois)}