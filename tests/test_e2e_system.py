import logging
import time
import pytest
from fastapi.testclient import TestClient

from papers.backend.main import app
from papers.backend.models import DownloadStatus
from papers.backend import deps

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%H:%M:%S",
    force=True
)
logger = logging.getLogger(__name__)

USER_HEADERS = {"X-User-ID": "e2e_test_researcher"}

def test_complete_system_lifecycle():
    app.dependency_overrides.clear()
    deps._global_db = None
    deps._global_settings = None

    with TestClient(app) as client:
        
        logger.info("Step 1: Verifying system health...")
        health_res = client.get("/health")
        assert health_res.status_code == 200

        logger.info("Step 2: Provisioning a Knowledge Base (Real DB)...")
        kb_payload = {"name": "E2E REAL AUDIT", "description": "Verified path"}
        kb_res = client.post("/api/v1/kbs", json=kb_payload, headers=USER_HEADERS)
        assert kb_res.status_code == 201
        kb_id = kb_res.json()["kb_id"]

        logger.info("Step 3: Triggering ingestion via API (Real Worker)...")
        target_doi = "10.1371/journal.pcbi.1003833"
        ingest_payload = {
            "doi": target_doi,
            "kb_id": kb_id,
            "title": "Ten Simple Rules for Better Figures"
        }

        ingest_res = client.post("/api/v1/ingestion/start", json=ingest_payload, headers=USER_HEADERS)
        assert ingest_res.status_code == 202
        ticket_id = ingest_res.json()["ticket_id"]

        logger.info(f"Step 4 & 5: Polling worker progress (Ticket: {ticket_id})...")
        for i in range(30):
            status_res = client.get(f"/api/v1/ingestion/status/{ticket_id}", headers=USER_HEADERS)
            status = status_res.json()["status"]
            
            logger.info(f"Iteration {i+1} - Worker status -> {status}")
            
            if status == DownloadStatus.COMPLETED.value:
                logger.info("SUCCESS: Ingestion completed by real background worker!")
                break
            elif status == DownloadStatus.FAILED.value:
                error_msg = status_res.json().get("error_message", "Unknown error")
                pytest.fail(f"Worker failed on real infrastructure: {error_msg}")
                
            time.sleep(2)
        else:
            pytest.fail("Timeout: The worker is not picking up the task from the real DB.")

        logger.info("Step 6: Final Semantic Search Verification...")
        search_query = "simple rules for better scientific figures"
        search_res = client.get(f"/api/v1/discovery/search?q={search_query}&limit=1", headers=USER_HEADERS)
        assert search_res.status_code == 200
        
        results = search_res.json()
        found = False
        for source, docs in results.items():
            if any(doc["doi"] == target_doi for doc in docs):
                found = True
                break
        assert found is True