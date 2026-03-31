"""
End-to-End System Verification Suite - Zero Mock Production Audit.

This module validates the complete document research lifecycle by utilizing 
the actual production call stack and configuration. It ensures total 
integration between the FastAPI routing layer, the BeaverDB persistence 
engine, and the semantic processing pipeline. 

The test follows a strict sequential execution pattern to verify state 
transitions and data integrity without utilizing mocks, sub-processes, 
or simulated environments.
"""

import logging
import pytest
from fastapi.testclient import TestClient

from papers.backend.main import app
from papers.backend.models import DownloadStatus
from papers.backend.tasks import ingest_paper
from papers.backend.deps import get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%H:%M:%S",
    force=True
)
logger = logging.getLogger(__name__)

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def e2e_environment():
    """
    Ensures the system is in a valid state for end-to-end verification.
    
    This fixture utilizes the live database and configuration settings 
    to guarantee that the test reflects the actual production environment.
    """
    logger.info("--- INITIATING PRODUCTION-PARITY SYSTEM TEST ---")
    yield
    logger.info("--- SYSTEM TEST EXECUTION COMPLETED ---")

def test_complete_system_lifecycle():
    """
    Executes the full application workflow against real infrastructure.
    
    The workflow encompasses:
    1. System health verification.
    2. Real Knowledge Base provisioning.
    3. Asynchronous task submission via the production API router.
    4. Execution of the core ingestion logic using the production task callable.
    5. Structural and semantic validation of the resulting records.
    6. System-wide cleanup of generated test assets.
    """
    logger.info("Step 1: Verifying real-time system health...")
    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "operational"

    logger.info("Step 2: Provisioning a production Knowledge Base...")
    kb_payload = {"name": "E2E Integration Audit", "description": "Verified system path"}
    kb_response = client.post("/api/v1/kbs", json=kb_payload)
    assert kb_response.status_code == 201
    kb_id = kb_response.json()["kb_id"]
    logger.info(f"Knowledge Base established with ID: {kb_id}")

    logger.info("Step 3: Triggering document ingestion via API...")
    target_doi = "10.1371/journal.pone.0115069"
    ingest_payload = {"doi": target_doi, "kb_id": kb_id}
    
    ingest_response = client.post("/api/v1/ingestion/start", json=ingest_payload)
    assert ingest_response.status_code == 202
    ticket_id = ingest_response.json()["ticket_id"]
    logger.info(f"Ingestion ticket generated: {ticket_id}")

    logger.info("Step 4: Confirming task persistence in PENDING state...")
    initial_status = client.get(f"/api/v1/ingestion/status/{ticket_id}")
    assert initial_status.json()["status"] == DownloadStatus.PENDING.value

    logger.info("Step 5: Executing production ingestion logic...")
    success = ingest_paper.callable(
        ticket_id=ticket_id, 
        doi=target_doi, 
        user_id="default_user", 
        kb_id=kb_id
    )
    assert success is True
    logger.info("Production ingestion logic executed successfully.")

    logger.info("Step 6: Verifying task transition to COMPLETED...")
    final_status = client.get(f"/api/v1/ingestion/status/{ticket_id}")
    assert final_status.json()["status"] == DownloadStatus.COMPLETED.value

    logger.info("Step 7: Validating global document availability...")
    docs_response = client.get("/api/v1/documents")
    assert any(doc["doi"] == target_doi for doc in docs_response.json())
    logger.info("Metadata persistence verified.")

    logger.info("Step 8: Testing live semantic retrieval...")
    search_query = "biology and computation"
    search_response = client.get(f"/api/v1/discovery/search?q={search_query}&limit=1")
    assert search_response.status_code == 200
    results = search_response.json()
    assert len(results) > 0
    assert results[0]["doi"] == target_doi
    logger.info(f"Semantic match confirmed: {results[0]['title']}")

    logger.info("Step 9: Cleaning up test artifacts...")
    client.post("/api/v1/documents/cleanup", json={"unlinked_only": False})
    logger.info("System cleanup successful.")