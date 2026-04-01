"""
Background worker tasks for asynchronous document ingestion.

This module isolates the heavy I/O bound operations (network downloading, 
HTML parsing, and fallback strategies) and CPU bound operations (semantic 
vector generation) from the main API thread. It ensures robust error 
handling and dynamic MIME type inference to maintain a format-agnostic pipeline.
"""
import asyncio
import httpx
import re
import logging
import mimetypes
from typing import Optional, Tuple
from castor import Manager
from beaver import BeaverDB

from papers.backend.config import Settings
from papers.backend.models import GlobalDocumentMeta, DownloadStatus
from papers.backend.data_sources import get_data_source
from papers.backend.storages import get_storage
from papers.backend.search import SemanticEngine

logger = logging.getLogger(__name__)

def get_task_infrastructure():
    """
    Bootstraps the required infrastructure within the worker execution context.
    """
    settings = Settings.load_from_yaml()
    db = BeaverDB(settings.database.file)
    return settings, db

manager = Manager(BeaverDB(Settings.load_from_yaml().database.file))

async def _download_asset(url: str, expected_mime: str) -> Tuple[bytes, str]:
    """
    Retrieves an academic asset and dynamically resolves its true MIME type.

    Employs a format-agnostic validation strategy. It strictly verifies PDF magic 
    bytes only when a PDF is claimed, handles HTML meta-tag redirection, and 
    natively accepts other arbitrary formats (EPUB, XML) based on server headers.
    """
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "curl/7.88.1",
        "Wget/1.21.2"
    ]

    logger.info(f"Starting asset acquisition sequence for URI: {url}")

    for agent in user_agents:
        headers = {
            "User-Agent": agent,
            "Accept": f"{expected_mime}, text/html, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive"
        }

        try:
            logger.info(f"Attempting connection with User-Agent: {agent[:15]}...")
            async with httpx.AsyncClient(follow_redirects=True, headers=headers, verify=False) as client:
                response = await client.get(url, timeout=45.0)
                
                raw_mime = response.headers.get("Content-Type", "application/octet-stream")
                resolved_mime = raw_mime.split(";")[0].strip().lower()
                logger.info(f"Received HTTP {response.status_code}. Content-Type: {resolved_mime}")

                if response.status_code not in (200, 201, 202):
                    logger.warning(f"Unacceptable HTTP status {response.status_code}. Rotating agent.")
                    continue

                if resolved_mime == "application/pdf":
                    if b"%PDF" in response.content[:2048]:
                        logger.info("Direct PDF binary signature verified.")
                        return response.content, resolved_mime
                    else:
                        logger.warning("Payload claims to be PDF but lacks magic bytes.")
                        continue

                elif "text/html" in resolved_mime:
                    logger.info("HTML payload detected. Initiating metadata extraction heuristics.")
                    meta_pattern = r'<meta[^>]*citation_pdf_url[^>]*>'
                    match = re.search(meta_pattern, response.text, re.IGNORECASE)
                    
                    if match:
                        meta_tag = match.group(0)
                        content_match = re.search(r'content\s*=\s*["\']([^"\']+)["\']', meta_tag, re.IGNORECASE)
                        
                        if content_match:
                            real_pdf_url = content_match.group(1)
                            if real_pdf_url.startswith("/"):
                                parsed_base = httpx.URL(url)
                                real_pdf_url = f"{parsed_base.scheme}://{parsed_base.host}{real_pdf_url}"
                                
                            logger.info(f"Extracted secondary URI: {real_pdf_url}. Initiating download.")
                            pdf_res = await client.get(real_pdf_url, timeout=45.0)
                            
                            sec_raw = pdf_res.headers.get("Content-Type", "application/octet-stream")
                            sec_mime = sec_raw.split(";")[0].strip().lower()
                            logger.info(f"Secondary URI HTTP Status: {pdf_res.status_code}. Content-Type: {sec_mime}")
                            
                            if pdf_res.status_code == 200:
                                if sec_mime == "application/pdf":
                                    if b"%PDF" in pdf_res.content[:2048]:
                                        logger.info("Secondary PDF binary signature verified.")
                                        return pdf_res.content, sec_mime
                                    else:
                                        logger.warning("Secondary payload claims PDF but lacks magic bytes.")
                                else:
                                    logger.info(f"Accepted secondary non-PDF payload natively: {sec_mime}")
                                    return pdf_res.content, sec_mime
                        else:
                            logger.warning("Matched meta tag lacked a valid content attribute.")
                    else:
                        logger.warning("No citation_pdf_url meta tag present in the HTML structure.")
                else:
                    logger.info(f"Accepted non-HTML payload natively: {resolved_mime}")
                    return response.content, resolved_mime

        except Exception as e:
            logger.error(f"Network subsystem failure: {type(e).__name__} - {str(e)}")
            continue

    raise ValueError(f"Asset acquisition failed for {url} across all agent strategies.")

async def _link_to_knowledge_base(doi: str, kb_id: str, kbs_db: dict) -> None:
    """
    Registers a document DOI within a specific knowledge base project.
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
    Coordinates the full document acquisition and semantic indexing lifecycle.
    """
    settings, db = get_task_infrastructure()
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
            source = get_data_source(source_name, settings=settings, db=db, user_id=user_id)
            meta = await source.fetch_by_doi(doi)
            if meta:
                break

        if not meta or not meta.storage_uri.startswith("http"):
            raise ValueError("Document metadata is restricted or unavailable.")

        try:
            asset_bytes, final_mime = await _download_asset(meta.storage_uri, meta.mime_type)
        except ValueError as primary_err:
            logger.warning(f"Primary storage URI failed: {primary_err}")
            logger.info(f"Initiating generic DOI resolution fallback for {doi}...")
            fallback_url = f"https://doi.org/{doi}"
            
            if fallback_url != meta.storage_uri:
                asset_bytes, final_mime = await _download_asset(fallback_url, meta.mime_type)
            else:
                raise primary_err

        if not asset_bytes:
            raise ValueError("Payload delivery failed or binary corrupted after all fallback attempts.")

        meta.mime_type = final_mime
        inferred_ext = mimetypes.guess_extension(final_mime)
        
        if final_mime == "application/pdf":
            meta.file_extension = ".pdf"
        elif inferred_ext:
            meta.file_extension = inferred_ext
        else:
            meta.file_extension = ""

        storage = get_storage(settings.storage.selected, base_path=settings.storage.local.base_path)
        safe_filename = f"{doi.replace('/', '_')}{meta.file_extension}"
        local_uri = await storage.save(safe_filename, asset_bytes)

        meta.storage_uri = local_uri
        meta.file_size = len(asset_bytes)
        
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
        error_details = f"{type(e).__name__}: {str(e) if str(e) else 'No explicit message'}"
        if ticket_id in downloads_db:
            req = downloads_db[ticket_id]
            req["status"] = DownloadStatus.FAILED.value
            req["error_message"] = error_details
            downloads_db[ticket_id] = req
        return False

@manager.task(mode='thread')
def ingest_paper(ticket_id: str, doi: str, user_id: str, kb_id: str) -> bool:
    """
    Entrypoint for the ingestion worker task.
    """
    return asyncio.run(_async_ingest(ticket_id, doi, user_id, kb_id))