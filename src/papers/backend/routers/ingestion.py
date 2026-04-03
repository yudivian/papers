"""
API router for asynchronous document ingestion and task monitoring.

This module provides the necessary endpoints to offload heavy network I/O 
and semantic processing to the Castor task queue. It enables a non-blocking 
client experience by issuing tracking tickets and providing status endpoints 
for real-time polling and historical task management.
"""

import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from beaver import BeaverDB

from papers.backend.deps import get_current_user, get_db
from papers.backend.models import DownloadStatus
from papers.backend.tasks import ingest_paper, manager
from papers.backend.config import Settings
from castor.core import TaskHandle

router = APIRouter()

class IngestionRequest(BaseModel):
    """
    Data Transfer Object for initiating a new document ingestion task.
    """
    doi: str
    kb_id: str
    title: Optional[str] = None
    
class IngestionResponse(BaseModel):
    """
    Data Transfer Object for returning the asynchronous tracking identifier.
    """
    ticket_id: str

class IngestionStatusResponse(BaseModel):
    """
    Data Transfer Object representing the current state of an ingestion task.
    """
    ticket_id: str
    doi: str    
    title: str  
    kb_id: str  
    status: str
    error_message: Optional[str] = None

@router.post("/start", response_model=IngestionResponse, status_code=202)
async def start_ingestion(
    payload: IngestionRequest,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> IngestionResponse:
    """
    Initiates the asynchronous download and processing pipeline.

    Generates a unique tracking ticket, registers the initial PENDING state 
    in the database, and dispatches the workload to the Castor task queue. 

    Args:
        payload: The request body containing the target DOI and destination Knowledge Base ID.
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        IngestionResponse: An object containing the generated tracking ticket ID.
    """
    ticket_id = str(uuid.uuid4())
    downloads_db = db.dict("downloads")
    
    display_title = payload.title if payload.title else f"Resolving DOI: {payload.doi}..."
    
    downloads_db[ticket_id] = {
        "status": DownloadStatus.PENDING.value,
        "doi": payload.doi,
        "title": display_title,
        "kb_id": payload.kb_id,
        "user_id": user_id
    }
    
    ingest_paper.submit(
        ticket_id=ticket_id, 
        doi=payload.doi, 
        user_id=user_id, 
        kb_id=payload.kb_id
    )
    
    return IngestionResponse(ticket_id=ticket_id)

@router.get("/status/{ticket_id}", response_model=IngestionStatusResponse)
async def get_ingestion_status(
    ticket_id: str,
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> IngestionStatusResponse:
    """
    Retrieves the current execution state of a previously submitted ingestion task.

    This endpoint is optimized for high-frequency polling from frontend clients 
    to provide real-time feedback on the download and vectorization progress.

    Args:
        ticket_id: The unique tracking identifier provided by the start endpoint.
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        IngestionStatusResponse: The current status of the task and any associated error messages.

    Raises:
        HTTPException: A 404 error if the ticket ID does not exist in the tracking database.
    """
    downloads_db = db.dict("downloads")
    ticket_data = downloads_db.get(ticket_id)
    
    if not ticket_data:
        raise HTTPException(
            status_code=404, 
            detail=f"Ingestion ticket '{ticket_id}' not found."
        )
        
    return IngestionStatusResponse(
        ticket_id=ticket_id,
        doi=ticket_data.get("doi", ""),
        title=ticket_data.get("title", "Unknown Title"),
        kb_id=ticket_data.get("kb_id", ""),
        status=ticket_data.get("status", DownloadStatus.PENDING.value),
        error_message=ticket_data.get("error_message")
    )

@router.get("/active", response_model=List[IngestionStatusResponse])
async def get_active_ingestions(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
) -> List[IngestionStatusResponse]:
    """
    Retrieves all user downloads that have not yet reached a terminal state.
    
    Enables the frontend client to restore its visual tracking state upon 
    page reload by identifying tasks still in progress.

    Args:
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        List[IngestionStatusResponse]: A list of task definitions currently being processed.
    """
    downloads_db = db.dict("downloads")
    active_tasks = []
    
    for ticket_id, data in downloads_db.items():
        if data.get("user_id") == user_id:
            status = data.get("status")
            if status in [DownloadStatus.PENDING.value, DownloadStatus.DOWNLOADING.value]:
                active_tasks.append(
                    IngestionStatusResponse(
                        ticket_id=ticket_id,
                        doi=data.get("doi", ""),
                        title=data.get("title", "Unknown Title"),
                        kb_id=data.get("kb_id", ""),
                        status=status
                    )
                )
                
    return active_tasks

@router.get("/tasks")
async def get_all_tasks(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
):
    """
    Retrieves the complete ingestion task history for the authenticated user.
    
    Iterates through the local storage dictionary and safely extracts records,
    ignoring malformed or legacy entries that lack proper user identification.

    Args:
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        List[dict]: A collection of task metadata dictionaries linked to the user.
    """
    downloads = db.dict("downloads")
    return [
        {**v, "ticket_id": k} 
        for k, v in downloads.items() 
        if v.get("user_id") == user_id
    ]

@router.post("/cancel/{ticket_id}")
async def cancel_task(
    ticket_id: str, 
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
):
    """
    Requests the termination of an active ingestion task.
    
    Communicates with the Castor task manager via TaskHandle to halt background 
    execution and updates the local database record to permanently register 
    the cancellation.

    Args:
        ticket_id: The unique tracking identifier of the target task.
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        dict: A status confirmation of the cancellation protocol.
    """
    TaskHandle(ticket_id, manager).cancel()
    
    downloads = db.dict("downloads")
    
    if ticket_id in downloads:
        item = downloads[ticket_id]
        if item.get("user_id") == user_id:
            item["status"] = "CANCELLED"
            downloads[ticket_id] = item
            
    return {"status": "ok"}

@router.post("/prune")
async def prune_tasks(
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
):
    """
    Purges completed, failed, and cancelled tasks to optimize local storage.
    
    Synchronizes the Castor internal memory structure with the BeaverDB storage 
    by enforcing retention strictly for tasks requiring active monitoring.

    Args:
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        dict: A status confirmation of the cleanup procedure.
    """
    manager.prune()
    downloads = db.dict("downloads")
    
    active_statuses = [DownloadStatus.PENDING.value, DownloadStatus.DOWNLOADING.value]
    new_downloads = {
        k: v for k, v in downloads.items() 
        if v.get("status") in active_statuses
    }
    
    db._data["downloads"] = new_downloads
    db.save()
    
    return {"status": "pruned"}

@router.delete("/{ticket_id}")
async def delete_task(
    ticket_id: str, 
    user_id: str = Depends(get_current_user),
    db: BeaverDB = Depends(get_db)
):
    """
    Permanently erases a single task record from the tracking database.
    
    Validates data ownership and prevents the deletion of active execution 
    processes without prior explicit cancellation.

    Args:
        ticket_id: The unique tracking identifier of the target task.
        user_id: The authenticated user's identifier, injected via dependencies.
        db: The active BeaverDB connection instance, injected via dependencies.

    Returns:
        dict: A status confirmation reflecting successful deletion.

    Raises:
        HTTPException: Denies operation if the task does not exist, belongs to 
                       another user, or is currently executing.
    """
    downloads = db.dict("downloads")
    
    if ticket_id not in downloads:
        raise HTTPException(status_code=404, detail="Task not found")
        
    task_data = downloads[ticket_id]
    
    if task_data.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    active_statuses = [DownloadStatus.PENDING.value, DownloadStatus.DOWNLOADING.value]
    if task_data.get("status") in active_statuses:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete an active task. Cancel it first."
        )
        
    del downloads[ticket_id]
    return {"status": "deleted"}