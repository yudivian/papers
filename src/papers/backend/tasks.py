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
import html
import urllib.parse
from curl_cffi.requests import AsyncSession
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
from papers.backend.deps import get_db

logger = logging.getLogger(__name__)

def get_task_infrastructure():
    """
    Bootstraps the required infrastructure within the worker execution context.
    """
    settings = Settings.load_from_yaml()
    db = get_db()
    return settings, db

manager = Manager(get_db())


async def _download_asset(url: str, expected_mime: str) -> Tuple[bytes, str]:
    """
    Retrieves an academic asset using a multi-tiered fallback strategy.
    Tier 1: Standard httpx (Fast, lightweight).
    Tier 2: curl_cffi TLS impersonation (Bypasses Cloudflare/DataDome on 403 Forbidden).
    """

    url_obj = httpx.URL(url)
    logger.info(f"Starting asset acquisition sequence for URI: {url}")

    # =========================================================================
    # PIPELINE CENTRAL DE EXTRACCIÓN (Agnóstico al cliente que lo ejecute)
    # =========================================================================
    async def _run_pipeline(client, is_antibot: bool) -> Tuple[bytes, str]:
        # Helper para detectar si nos bloqueó el WAF (Firewall)
        def check_block(status):
            if status in (401, 403, 429, 503):
                raise ValueError(f"BotBlocked:{status}")

        response = await client.get(url, timeout=45.0)
        check_block(response.status_code)
        
        raw_mime = response.headers.get("Content-Type", "application/octet-stream")
        resolved_mime = raw_mime.split(";")[0].strip().lower()

        is_pdf_bytes = b"%PDF" in response.content[:2048]

        if is_pdf_bytes:
            logger.info("Direct PDF binary signature verified.")
            return response.content, "application/pdf"
        elif resolved_mime == "application/pdf":
            if b"<html" in response.content[:2048].lower():
                resolved_mime = "text/html"
            else:
                raise ValueError("Payload claims to be PDF but lacks magic bytes.")

        if "text/html" in resolved_mime:
            html_text = response.text
            
            # 1. RESOLVER TRAMPA DEL NAVEGADOR Y DESEMPAQUETAR REDIRECCIONES
            meta_redirects = 0
            while "text/html" in resolved_mime and meta_redirects < 3:
                if "http-equiv=\"refresh\"" in html_text.lower() or "http-equiv=refresh" in html_text.lower():
                    match = re.search(r'url=[\'"]?([^\'">\s]+)', html_text, re.IGNORECASE)
                    if match:
                        refresh_url = html.unescape(match.group(1).strip())
                        
                        try:
                            parsed_refresh = urllib.parse.urlparse(refresh_url)
                            query_params = urllib.parse.parse_qs(parsed_refresh.query)
                            for key, vals in query_params.items():
                                if vals and vals[0].startswith("http"):
                                    refresh_url = vals[0] 
                                    logger.info(f"Unwrapped embedded redirect target: {refresh_url}")
                                    break
                        except Exception:
                            pass
                        
                        if refresh_url.startswith("/"):
                            current_url = str(response.url)
                            base_url_obj = httpx.URL(current_url)
                            refresh_url = f"{base_url_obj.scheme}://{base_url_obj.host}{refresh_url}"
                            
                        logger.info(f"Meta Refresh detectado. Saltando a la URL real...")
                        
                        response = await client.get(refresh_url, timeout=45.0)
                        check_block(response.status_code) # ¿Nos dio 403 el destino?
                        
                        html_text = response.text
                        raw_mime = response.headers.get("Content-Type", "application/octet-stream")
                        resolved_mime = raw_mime.split(";")[0].strip().lower()
                        meta_redirects += 1
                        continue
                break

            if resolved_mime == "application/pdf" or b"%PDF" in response.content[:2048]:
                return response.content, "application/pdf"

            final_url = str(response.url)
            final_url_obj = httpx.URL(final_url)
            candidates = []

            # 2. METADATOS ESTÁNDAR
            meta_patterns = [
                r'(?:name|property)\s*=\s*["\']citation_pdf_url["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
                r'content\s*=\s*["\']([^"\']+)["\'][^>]*(?:name|property)\s*=\s*["\']citation_pdf_url["\']'
            ]
            for pattern in meta_patterns:
                match = re.search(pattern, html_text, re.IGNORECASE)
                if match:
                    candidates.append(html.unescape(match.group(1)))

            # 3. BÚSQUEDA CIEGA (Para React/Vue JSON y links genéricos)
            if not candidates:
                potential_links = re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html_text, re.IGNORECASE)
                potential_links += re.findall(r'["\'](https?://[^"\']+)["\']', html_text, re.IGNORECASE)
                potential_links += re.findall(r'["\'](/[a-zA-Z0-9_.-]+/[^"\']+)["\']', html_text, re.IGNORECASE)
                
                for link in potential_links:
                    link_clean = html.unescape(link).strip()
                    link_lower = link_clean.lower()
                    base_path = link_lower.split("?")[0]
                    if "pdf" in link_lower and not base_path.endswith((".html", ".htm", ".php", ".aspx")):
                        candidates.append(link_clean)
                        
                if candidates:
                    candidates = list(dict.fromkeys(candidates))[:8]

            if not candidates:
                raise ValueError("No PDF candidates found in HTML.")

            # 4. DESCARGA SECUNDARIA DE CANDIDATOS
            for real_pdf_url in candidates:
                if real_pdf_url.startswith("/"):
                    base_scheme = final_url_obj.scheme or url_obj.scheme
                    base_host = final_url_obj.host or url_obj.host
                    real_pdf_url = f"{base_scheme}://{base_host}{real_pdf_url}"
                    
                logger.info(f"Testing candidate URI: {real_pdf_url}")
                try:
                    pdf_res = await client.get(real_pdf_url, headers={"Referer": final_url}, timeout=45.0)
                    check_block(pdf_res.status_code) # ¿Nos dio 403 al descargar el PDF?
                    
                    sec_raw = pdf_res.headers.get("Content-Type", "application/octet-stream")
                    sec_mime = sec_raw.split(";")[0].strip().lower()
                    
                    if pdf_res.status_code == 200:
                        if sec_mime == "application/pdf" or b"%PDF" in pdf_res.content[:2048]:
                            logger.info("Secondary PDF binary signature verified. SUCCESS.")
                            return pdf_res.content, "application/pdf"
                except ValueError as ve:
                    if "BotBlocked" in str(ve):
                        raise ve # Escala el 403 hacia arriba para cambiar de cliente
                    continue
                except Exception:
                    continue
                    
            raise ValueError("All candidates failed.")
        else:
            return response.content, resolved_mime

    # =========================================================================
    # TIER 1: HTTPX (Rápido, ligero, ideal para ArXiv, PLOS, etc.)
    # =========================================================================
    standard_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": f"{expected_mime}, text/html, application/xhtml+xml, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    logger.info("STRATEGY 1: Standard HTTPX Client")
    try:
        async with httpx.AsyncClient(follow_redirects=True, headers=standard_headers, verify=False) as httpx_client:
            return await _run_pipeline(httpx_client, is_antibot=False)
    except ValueError as e:
        if "BotBlocked" in str(e):
            logger.warning(f"HTTPX blocked by WAF ({str(e)}). Escalating to Anti-Bot Strategy.")
        else:
            logger.info(f"HTTPX strategy failed normally: {e}. Escalating to Anti-Bot Strategy.")
    except Exception as e:
        logger.info(f"HTTPX strategy network error: {e}. Escalating to Anti-Bot Strategy.")

    # =========================================================================
    # TIER 2: CURL_CFFI (Pesado, Suplantación TLS contra Cloudflare/DataDome)
    # =========================================================================
    logger.warning("STRATEGY 2: TLS Impersonation (curl_cffi - Chrome 110)")
    try:
        async with AsyncSession(impersonate="chrome110", verify=False) as curl_client:
            return await _run_pipeline(curl_client, is_antibot=True)
    except Exception as e:
        logger.error(f"Anti-Bot strategy also failed: {e}")

    raise ValueError(f"Asset acquisition failed for {url} across all strategies.")

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

        if not meta:
            raise ValueError("Document metadata is unavailable.")

        # Manejamos las URLs candidatas en un pipeline para evitar el bug del fallback circular
        primary_url = meta.storage_uri or ""
        urls_to_try = []

        if primary_url.startswith("http"):
            urls_to_try.append(primary_url)

        # CORTAFUEGOS 1: Añadimos el fallback solo si es un DOI oficial
        is_official = getattr(meta, "is_official_doi", True)
        if is_official:
            # CORE puede devolver un DOI real aunque hayamos buscado por un ID interno.
            # Usamos el DOI del meta si existe y es real, de lo contrario usamos el argumento original.
            actual_doi = meta.doi if (meta.doi and not meta.doi.startswith("core:")) else doi
            
            if not actual_doi.startswith("core:"):
                doi_fallback_url = f"https://doi.org/{actual_doi}"
                if doi_fallback_url not in urls_to_try:
                    urls_to_try.append(doi_fallback_url)

        # Si no hay link de storage ni es un DOI oficial, abortamos
        if not urls_to_try:
            raise ValueError("El documento es un registro de metadatos sin enlace de descarga oficial ni directo.")

        asset_bytes = None
        final_mime = None
        last_error = None

        # Bucle de intentos: Primero intenta la fuente primaria (OpenAlex), si falla intenta el DOI
        for target_url in urls_to_try:
            try:
                logger.info(f"Attempting download pipeline with target: {target_url}")
                asset_bytes, final_mime = await _download_asset(target_url, meta.mime_type)
                if asset_bytes:
                    break  # Éxito: Salimos del bucle
            except ValueError as err:
                logger.warning(f"Target URI failed: {err}")
                last_error = err
                continue

        # CORTAFUEGOS 2: Fallo total
        if not asset_bytes:
            if not is_official:
                logger.error(f"❌ Abortando: '{doi}' no es oficial. No se buscaron fallbacks globales.")
                raise ValueError("Descarga directa fallida. Identificador propietario sin rescate posible.")
            else:
                raise ValueError(f"Payload delivery failed after all fallback attempts. Last error: {last_error}")

        meta.mime_type = final_mime
        inferred_ext = mimetypes.guess_extension(final_mime)
        
        if final_mime == "application/pdf":
            meta.file_extension = ".pdf"
        elif inferred_ext:
            meta.file_extension = inferred_ext
        else:
            meta.file_extension = ""

        storage = get_storage(settings.storage.selected, base_path=settings.storage.local.base_path)
        final_identifier = meta.doi if meta.doi else doi
        safe_filename = f"{final_identifier.replace('/', '_').replace(':', '_')}{meta.file_extension}"
        local_uri = await storage.save(safe_filename, asset_bytes)
        

        meta.storage_uri = local_uri
        meta.file_size = len(asset_bytes)
        
        docs_db[final_identifier] = meta.model_dump(mode="json")
        
        if final_identifier not in vectors_db:
            engine = SemanticEngine()
            text_context = engine.build_semantic_text(meta)
            vector = engine.generate_embedding(text_context)
            
            vectors_db[final_identifier] = {
                "doi": final_identifier,
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