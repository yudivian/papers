import logging
import time
import pytest
from fastapi.testclient import TestClient

from papers.backend.main import app
from papers.backend.models import DownloadStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%H:%M:%S",
    force=True
)
logger = logging.getLogger(__name__)

USER_HEADERS = {"X-User-ID": "e2e_test_researcher"}

@pytest.fixture(scope="module")
def real_client():
    """
    Usar TestClient como context manager (with) es CRÍTICO para un E2E real.
    Esto obliga a FastAPI a disparar los eventos de 'startup' y 'lifespan',
    lo que enciende los workers de Castor en segundo plano de forma nativa.
    """
    logger.info("--- INITIATING PRODUCTION-PARITY SYSTEM TEST ---")
    with TestClient(app) as client:
        yield client
    logger.info("--- SYSTEM TEST EXECUTION COMPLETED ---")


def test_complete_system_lifecycle(real_client):
    """
    Validates the end-to-end research workflow using live production infrastructure.
    """
    logger.info("Step 1: Verifying system health...")
    health_response = real_client.get("/health")
    assert health_response.status_code == 200

    logger.info("Step 2: Provisioning a production Knowledge Base...")
    kb_payload = {"name": "E2E Audit", "description": "Verified path"}
    kb_res = real_client.post("/api/v1/kbs", json=kb_payload, headers=USER_HEADERS)
    assert kb_res.status_code == 201
    kb_id = kb_res.json()["kb_id"]

    logger.info("Step 3: Triggering ingestion via API (Real Background Queue)...")
    target_doi = "10.1371/journal.pone.0115069"
    ingest_payload = {
        "doi": target_doi,
        "kb_id": kb_id,
        "title": "Ten Simple Rules for Better Figures"
    }

    ingest_res = real_client.post("/api/v1/ingestion/start", json=ingest_payload, headers=USER_HEADERS)
    assert ingest_res.status_code == 202
    ticket_id = ingest_res.json()["ticket_id"]

    logger.info("Step 4 & 5: Polling real background worker progress...")
    max_retries = 20
    for _ in range(max_retries):
        status_res = real_client.get(f"/api/v1/ingestion/status/{ticket_id}", headers=USER_HEADERS)
        status = status_res.json()["status"]
        
        logger.info(f"Worker status -> {status}")
        
        if status == DownloadStatus.COMPLETED.value:
            logger.info("Ingestion successfully completed by worker!")
            break
        elif status == DownloadStatus.FAILED.value:
            error_msg = status_res.json().get("error_message", "Unknown error")
            pytest.fail(f"Background worker failed during ingestion: {error_msg}")
            
        time.sleep(2)  # Damos respiro al hilo de Castor
    else:
        pytest.fail("The background worker did not complete the ingestion in time. Is the worker thread running?")

    logger.info("Step 6: Testing classified semantic retrieval...")
    search_query = "simple rules for better scientific figures"
    search_res = real_client.get(f"/api/v1/discovery/search?q={search_query}&limit=1", headers=USER_HEADERS)
    assert search_res.status_code == 200
    
    results = search_res.json()
    assert isinstance(results, dict)
    
    found = False
    for source, docs in results.items():
        if any(doc["doi"] == target_doi for doc in docs):
            found = True
            break
            
    assert found is True