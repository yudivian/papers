import logging
import pytest
from fastapi.testclient import TestClient

from papers.backend.main import app
from papers.backend.models import DownloadStatus
from papers.backend.tasks import ingest_paper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%H:%M:%S",
    force=True
)
logger = logging.getLogger(__name__)

client = TestClient(app)
USER_HEADERS = {"X-User-ID": "e2e_test_researcher"}

@pytest.fixture(scope="module", autouse=True)
def e2e_environment():
    """
    Ensures the execution context is logged for production-parity verification.
    """
    logger.info("--- INITIATING PRODUCTION-PARITY SYSTEM TEST ---")
    yield
    logger.info("--- SYSTEM TEST EXECUTION COMPLETED ---")

def test_complete_system_lifecycle():
    """
    Validates the end-to-end research workflow using live production infrastructure.

    Workflow:
    1. Liveness check.
    2. JIT provisioning of a Knowledge Base.
    3. Asynchronous ingestion dispatch.
    4. Worker execution of the acquisition and semantic pipeline.
    5. Classified semantic search validation.
    6. System cleanup.
    """
    logger.info("Step 1: Verifying system health...")
    health_response = client.get("/health")
    assert health_response.status_code == 200

    logger.info("Step 2: Provisioning a production Knowledge Base...")
    kb_payload = {"name": "E2E Audit", "description": "Verified path"}
    kb_res = client.post("/api/v1/kbs", json=kb_payload, headers=USER_HEADERS)
    assert kb_res.status_code == 201
    kb_id = kb_res.json()["kb_id"]

    logger.info("Step 3: Triggering ingestion via API...")
    target_doi = "10.1371/journal.pone.0115069"
    ingest_payload = {"doi": target_doi, "kb_id": kb_id}
    
    ingest_res = client.post("/api/v1/ingestion/start", json=ingest_payload, headers=USER_HEADERS)
    assert ingest_res.status_code == 202
    ticket_id = ingest_res.json()["ticket_id"]

    logger.info("Step 4: Executing production ingestion logic...")
    success = ingest_paper.callable(
        ticket_id=ticket_id, 
        doi=target_doi, 
        user_id="e2e_test_researcher", 
        kb_id=kb_id
    )
    assert success is True

    logger.info("Step 5: Verifying completion status...")
    status_res = client.get(f"/api/v1/ingestion/status/{ticket_id}", headers=USER_HEADERS)
    assert status_res.json()["status"] == DownloadStatus.COMPLETED.value

    logger.info("Step 6: Testing classified semantic retrieval...")
    search_query = "biology and computation"
    search_res = client.get(f"/api/v1/discovery/search?q={search_query}&limit=1", headers=USER_HEADERS)
    assert search_res.status_code == 200
    
    results = search_res.json()
    assert isinstance(results, dict)
    
    found = False
    for source, docs in results.items():
        if any(doc["doi"] == target_doi for doc in docs):
            found = True
            break
    assert found is True

    logger.info("Step 7: Executing system cleanup...")
    client.post("/api/v1/documents/cleanup", json={"unlinked_only": False}, headers=USER_HEADERS)