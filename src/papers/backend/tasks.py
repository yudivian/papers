"""
Core asynchronous task orchestration module for the document ingestion pipeline.

This module acts as the boundary between the synchronous Castor task queue and 
the highly concurrent, I/O-bound operations required to fetch, process, and 
store academic papers. It enforces a strict state machine for tracking download 
progress via the `DownloadRequest` model, ensuring the frontend can poll for 
real-time updates without directly querying the task queue infrastructure.

State Machine Flow:
    1. Caller inserts DownloadRequest (PENDING) and submits the Castor task.
    2. Worker picks up task -> Transitions ticket to DOWNLOADING.
    3. Pipeline resolves metadata and downloads physical PDF binary.
    4. On success -> Transitions ticket to COMPLETED, creates GlobalDocumentMeta.
    5. On failure -> Transitions ticket to FAILED, records error payload.
"""

import asyncio
import httpx
from typing import Optional
from castor import Manager
from beaver import BeaverDB

from papers.backend.config import Settings
from papers.backend.models import GlobalDocumentMeta, DownloadStatus
from papers.backend.data_sources import get_data_source
from papers.backend.storages import get_storage
from papers.backend.search import SemanticEngine

settings = Settings.load_from_yaml()
db = BeaverDB(settings.database.file)
manager = Manager(db)

async def _download_pdf(url: str, doi: str) -> Optional[bytes]:
    """
    Executes a fortified, asynchronous HTTP GET request to retrieve PDF binaries.

    This function implements specific evasion heuristics and payload validation 
    to navigate the complexities of academic web scraping. It actively rewrites 
    known HTML landing page URLs into their direct PDF endpoints (e.g., Arxiv) 
    and spoofs standard browser User-Agents to bypass rudimentary 403 Forbidden 
    blocks from major publishers. 

    Furthermore, it enforces binary integrity by reading the magic bytes of the 
    response payload, discarding payloads that return HTTP 200 OK but contain 
    Captchas, paywall HTMLs, or proxy errors.

    Args:
        url: The candidate storage URI provided by the metadata resolution phase.
        doi: The Digital Object Identifier used to infer repository heuristics.

    Returns:
        Optional[bytes]: The raw, validated PDF byte sequence if successful; 
                         None if the network times out, the server blocks the 
                         request, or the payload fails binary validation.
    """
    if "arxiv." in doi.lower():
        arxiv_id = doi.split("arxiv.")[-1]
        url = f"https://export.arxiv.org/pdf/{arxiv_id}.pdf"
    elif "arxiv.org/abs/" in url:
        url = url.replace("arxiv.org/abs/", "export.arxiv.org/pdf/")
        if not url.endswith(".pdf"):
            url += ".pdf"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/pdf"
    }

    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        try:
            response = await client.get(url, timeout=30.0)
            if response.status_code == 200:
                if response.content.startswith(b"%PDF"):
                    return response.content
        except httpx.HTTPError:
            pass
            
    return None

async def _link_to_knowledge_base(doi: str, kb_id: str, kbs_db: dict) -> None:
    """
    Establishes a logical association between a global document and a user project.

    This operation is designed to be idempotent. It safely modifies the list of 
    document identifiers within a specific Knowledge Base record, preventing 
    duplicate associations if the linkage is triggered multiple times due to 
    cache hits or task retries.

    Args:
        doi: The unique Digital Object Identifier of the ingested document.
        kb_id: The target identifier of the user's Knowledge Base.
        kbs_db: The injected BeaverDB dictionary reference for the kbs collection.
    """
    if kb_id in kbs_db:
        kb_data = kbs_db[kb_id]
        document_ids = kb_data.get("document_ids", [])
        if doi not in document_ids:
            document_ids.append(doi)
            kb_data["document_ids"] = document_ids
            kbs_db[kb_id] = kb_data

async def _async_ingest(ticket_id: str, doi: str, user_id: str, kb_id: str) -> bool:
    """
    Orchestrates the entire end-to-end lifecycle of a document ingestion request.

    This coroutine governs the transactional boundary of the ingestion process. 
    It is responsible for transitioning the `DownloadRequest` tracking state, 
    querying the local semantic cache to prevent redundant network I/O, resolving 
    global metadata through prioritized external adapters, executing the binary 
    download, and persisting the resulting payload to the configured storage backend.

    Any unhandled exceptions during metadata resolution or binary retrieval are 
    caught, converted into string payloads, and written back to the `DownloadRequest` 
    record to provide immediate upstream observability to the frontend clients.

    Args:
        ticket_id: The tracking UUID of the DownloadRequest record.
        doi: The target Digital Object Identifier to ingest.
        user_id: The unique identifier of the requesting entity.
        kb_id: The target Knowledge Base destination for the final linkage.

    Returns:
        bool: True if the document was successfully acquired and linked, or if 
              it was fulfilled via local cache. False if the network layer failed, 
              the document is paywalled, or a storage violation occurred.
    """
    docs_db = db.dict("global_documents")
    kbs_db = db.dict("knowledge_bases")
    downloads_db = db.dict("downloads")
    vectors_db = db.dict("semantic_vectors")

    if ticket_id in downloads_db:
        req = downloads_db[ticket_id]
        req["status"] = DownloadStatus.DOWNLOADING.value
        downloads_db[ticket_id] = req
        
    try:
        if doi in docs_db:
            await _link_to_knowledge_base(doi, kb_id, kbs_db)
            if ticket_id in downloads_db:
                req = downloads_db[ticket_id]
                req["status"] = DownloadStatus.COMPLETED.value
                downloads_db[ticket_id] = req
            return True

        meta: Optional[GlobalDocumentMeta] = None
        for source_name in settings.data_sources.priority:
            source = get_data_source(
                source_name, 
                settings=settings,
                db=db,
                user_id=user_id
            )
            meta = await source.fetch_by_doi(doi)
            if meta:
                break

        if not meta or not meta.storage_uri.startswith("http"):
            raise ValueError("Target document is either non-existent or restricted behind a closed access paywall.")

        pdf_bytes = await _download_pdf(meta.storage_uri, doi)
        if not pdf_bytes:
            raise ValueError("Upstream repository blocked the download request or returned a corrupted payload.")

        storage = get_storage(
            settings.storage.selected, 
            base_path=settings.storage.local.base_path
        )
        safe_filename = f"{doi.replace('/', '_')}.pdf"
        local_uri = await storage.save(safe_filename, pdf_bytes)

        meta.storage_uri = local_uri
        meta.file_size = len(pdf_bytes)
        
        docs_db[doi] = meta.model_dump(mode="json")
        if doi not in vectors_db:
            engine = SemanticEngine()
            text_context = engine.build_semantic_text(meta)
            vector = engine.generate_embedding(text_context)
            
            vectors_db[doi] = {
                "doi": doi,
                "vector": vector,
                "text_chunk": text_context 
            }
        await _link_to_knowledge_base(doi, kb_id, kbs_db)
        
        if ticket_id in downloads_db:
            req = downloads_db[ticket_id]
            req["status"] = DownloadStatus.COMPLETED.value
            downloads_db[ticket_id] = req
            
        return True

    except Exception as e:
        if ticket_id in downloads_db:
            req = downloads_db[ticket_id]
            req["status"] = DownloadStatus.FAILED.value
            req["error_message"] = str(e)
            downloads_db[ticket_id] = req
        return False

@manager.task(mode='thread')
def ingest_paper(ticket_id: str, doi: str, user_id: str, kb_id: str) -> bool:
    """
    Synchronous Castor execution boundary for the ingestion pipeline.

    Since the castor-io infrastructure dispatches tasks using a standard 
    ThreadPoolExecutor, this function serves as the critical bridge to spawn 
    a localized asynchronous event loop. It delegates the execution of the 
    I/O-heavy orchestration to the underlying asyncio engine, preventing 
    thread blocking and ensuring non-blocking network requests.

    Args:
        ticket_id: Identifier mapped to the frontend's pending DownloadRequest.
        doi: Target document identifier.
        user_id: Requester identity for audit and access control.
        kb_id: Destination namespace for the document pointer.

    Returns:
        bool: State of the ingestion pipeline execution.
    """
    return asyncio.run(_async_ingest(ticket_id, doi, user_id, kb_id))