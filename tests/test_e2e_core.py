import logging
import time
import pytest
from fastapi.testclient import TestClient

from papers.backend.main import app
from papers.backend.models import DownloadStatus
from papers.backend import deps
from papers.backend.tasks import manager

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - [%(levelname)s] - %(message)s", 
    datefmt="%H:%M:%S",
    force=True
)
logger = logging.getLogger(__name__)

USER_HEADERS = {"X-User-ID": "e2e_core_researcher"}

def test_core_system_workflow():
    app.dependency_overrides.clear()
    deps._global_db = None
    deps._global_settings = None
    
    real_db = deps.get_db()
    manager._db = real_db

    logger.info("--- INICIO E2E CORE REAL (PERSISTENTE) ---")

    with TestClient(app) as client:
        
        search_query = "query-biased summaries for question answering"
        logger.info(f"Step 1: Searching CORE for: {search_query}")
        
        discovery_res = client.get(
            f"/api/v1/discovery/search?q={search_query}&limit=1", 
            headers=USER_HEADERS
        )
        assert discovery_res.status_code == 200
        
        results = discovery_res.json()
        core_docs = results.get("core", [])
        assert len(core_docs) > 0, "No se encontraron resultados en CORE. Revisa tu API Key."
        
        target_doc = core_docs[0]
        target_id = target_doc["doi"]
        target_title = target_doc.get("title")
        logger.info(f"Target found: {target_id} - {target_title}")
        logger.info("Step 2: Starting ingestion into real DB...")
        kb_payload = {"name": "E2E CORE Real", "description": "Verificación de caché local"}
        kb_res = client.post("/api/v1/kbs", json=kb_payload, headers=USER_HEADERS)
        kb_id = kb_res.json()["kb_id"]
        
        ingest_payload = {
            "doi": target_id, 
            "kb_id": kb_id,
            "title": target_title
        }
        ingest_res = client.post("/api/v1/ingestion/start", json=ingest_payload, headers=USER_HEADERS)    
        assert ingest_res.status_code == 202
        ticket_id = ingest_res.json()["ticket_id"]

        logger.info(f"Step 3: Polling worker progress (Ticket: {ticket_id})...")
        for i in range(25):
            status_res = client.get(f"/api/v1/ingestion/status/{ticket_id}", headers=USER_HEADERS)
            status = status_res.json()["status"]
            logger.info(f"Iteration {i+1} - Status: {status}")
            
            if status == DownloadStatus.COMPLETED.value:
                logger.info("Ingestion completed successfully!")
                break
            elif status == DownloadStatus.FAILED.value:
                pytest.fail(f"Worker failed: {status_res.json().get('error_message')}")
            time.sleep(3)
        else:
            pytest.fail("Timeout: The worker did not finish the ingestion.")

        logger.info(f"Step 4: Verifying semantic retrieval in 'cache' for: {target_title}")
        
        retrieval_res = client.get(
            f"/api/v1/discovery/search?q={target_title}&limit=49", 
            headers=USER_HEADERS
        )
        assert retrieval_res.status_code == 200
        
        cache_results = retrieval_res.json().get("cache", [])
        
        found = any(target_id == d["doi"] for d in cache_results)
        
        if not found:
            logger.error(f"Document {target_id} not found in cache results.")
            logger.info(f"Results in cache: {[d['doi'] for d in cache_results]}")
            assert found, "El documento se ingirió pero la búsqueda en caché no lo recupera."

    logger.info("--- TEST E2E CORE PASSED ---")