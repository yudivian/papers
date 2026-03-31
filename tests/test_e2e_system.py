"""
End-to-End System Verification Suite.

This module executes a completely unmocked, real-world scenario spanning 
the entire system architecture. It utilizes a globally patched configuration 
to isolate the database and storage on a temporary filesystem while allowing 
all network adapters, asynchronous background tasks, and AI vectorization 
engines to operate exactly as they would in a production environment.
"""

import os
import time
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from papers.backend.main import app
from papers.backend.models import DownloadStatus
from papers.backend.config import Settings

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def e2e_environment():
    """
    Provisions a globally isolated environment for the E2E testing lifecycle.
    
    Instead of overriding FastAPI dependencies, this fixture directly patches 
    the configuration loader. This guarantees that both the synchronous API 
    endpoints and the asynchronous background workers connect to the same 
    temporary database and storage paths, preventing state desynchronization.
    
    Yields:
        None
    """
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "e2e_system.db")
    storage_path = os.path.join(temp_dir, "e2e_pdfs")
    os.makedirs(storage_path)
    
    original_loader = Settings.load_from_yaml

    def override_load_from_yaml():
        settings = original_loader()
        settings.database.file = db_path
        settings.storage.local.base_path = storage_path
        return settings

    with patch("papers.backend.config.Settings.load_from_yaml", side_effect=override_load_from_yaml):
        yield

    shutil.rmtree(temp_dir)

def test_complete_system_lifecycle():
    """
    Executes the full application workflow against real external infrastructure.
    
    The workflow encompasses:
    1. System health verification.
    2. Knowledge Base provisioning.
    3. Asynchronous ingestion of a real, Open Access DOI.
    4. Task queue polling until successful resolution and vectorization.
    5. Structural validation of the resulting database records.
    6. Contextual semantic retrieval using the AI engine.
    7. Global cleanup and physical asset purging.
    """
    health_response = client.get("/health")
    assert health_response.status_code == 200

    kb_payload = {"name": "E2E Integration Project", "description": ""}
    kb_response = client.post("/api/v1/kbs", json=kb_payload)
    assert kb_response.status_code == 201
    kb_id = kb_response.json()["kb_id"]

    target_doi = "10.1371/journal.pone.0115069"
    ingest_payload = {"doi": target_doi, "kb_id": kb_id}
    
    ingest_response = client.post("/api/v1/ingestion/start", json=ingest_payload)
    assert ingest_response.status_code == 202
    ticket_id = ingest_response.json()["ticket_id"]

    max_retries = 30
    poll_interval = 2
    final_status = None

    for _ in range(max_retries):
        status_response = client.get(f"/api/v1/ingestion/status/{ticket_id}")
        assert status_response.status_code == 200
        current_status = status_response.json()["status"]
        
        if current_status in [DownloadStatus.COMPLETED.value, DownloadStatus.FAILED.value]:
            final_status = current_status
            break
            
        time.sleep(poll_interval)

    assert final_status == DownloadStatus.COMPLETED.value

    docs_response = client.get("/api/v1/documents")
    assert docs_response.status_code == 200
    docs = docs_response.json()
    assert len(docs) == 1
    assert docs[0]["doi"] == target_doi

    kb_detail_response = client.get(f"/api/v1/kbs/{kb_id}")
    assert kb_detail_response.status_code == 200
    assert len(kb_detail_response.json()["documents"]) == 1

    search_response = client.get("/api/v1/discovery/search?q=biology and computation&limit=1")
    assert search_response.status_code == 200
    search_results = search_response.json()
    assert len(search_results) > 0
    assert search_results[0]["doi"] == target_doi

    cleanup_response = client.post("/api/v1/documents/cleanup", json={"unlinked_only": False})
    assert cleanup_response.status_code == 200
    assert cleanup_response.json()["deleted_count"] == 1

    final_docs_response = client.get("/api/v1/documents")
    assert len(final_docs_response.json()) == 0