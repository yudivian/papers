import logging
import time
import pytest
from fastapi.testclient import TestClient
from papers.backend.main import app
from papers.backend.models import DownloadStatus
from papers.backend.deps import get_settings
import importlib
from papers.backend.config import Settings

logger = logging.getLogger(__name__)
USER_HEADERS = {"X-User-ID": "e2e_core_researcher"}



# --- DEJA SOLO ESTE ---
@pytest.fixture
def core_e2e_client(live_app_client):
    """
    Usa el cliente global, pero inyecta la prioridad 'core' solo para este test.
    """
    test_settings = Settings.load_from_yaml()
    test_settings.data_sources.priority = ["cache", "core"]
    
    # --- AÑADE ESTA LÍNEA PARA EVITAR QUE EL TEST SE BLOQUEE A SÍ MISMO ---
    test_settings.data_sources.core.daily_search_limit = 99999
    
    app.dependency_overrides[get_settings] = lambda: test_settings
    
    yield live_app_client
    
    app.dependency_overrides.clear()

def test_core_system_workflow(core_e2e_client):
    """
    Validates the end-to-end research workflow specifically using CORE.
    """
    # 1. Discovery: Search for a known paper in CORE
    search_query = "query-biased summaries for question answering"
    search_res = core_e2e_client.get(f"/api/v1/discovery/search?q={search_query}&limit=1", headers=USER_HEADERS)
    assert search_res.status_code == 200
    
    results = search_res.json()
    core_docs = results.get("core", [])
    assert len(core_docs) > 0, "No results found in CORE for the E2E test."
    
    target_doc = core_docs[0]
    target_id = target_doc["doi"] # In CORE this might be 'core:4190558'
    
    # 2. Ingestion: Trigger background task
    kb_payload = {"name": "CORE Audit", "description": "E2E CORE Path"}
    kb_res = core_e2e_client.post("/api/v1/kbs/", json=kb_payload, headers=USER_HEADERS)
    kb_id = kb_res.json()["kb_id"]
    
    ingest_payload = {"doi": target_id, "kb_id": kb_id}
    # Línea corregida
    ingest_res = core_e2e_client.post("/api/v1/ingestion/start", json=ingest_payload, headers=USER_HEADERS)    
    assert ingest_res.status_code == 202
    ticket_id = ingest_res.json()["ticket_id"]

    # 3. Polling: Wait for Castor worker to finish
    max_retries = 15
    completed = False
    for _ in range(max_retries):
        status_res = core_e2e_client.get(f"/api/v1/ingestion/status/{ticket_id}", headers=USER_HEADERS)
        status = status_res.json()["status"]
        if status == DownloadStatus.COMPLETED.value:
            completed = True
            break
        time.sleep(3)
    
    assert completed, "CORE Ingestion did not complete in time."

    # 4. Retrieval: Verify semantic presence
    search_query = "query-biased summaries"
    retrieval_res = core_e2e_client.get(f"/api/v1/discovery/search?q={search_query}&limit=5", headers=USER_HEADERS)
    cache_results = retrieval_res.json().get("cache", [])
    assert any(d["doi"] == target_id for d in cache_results), "Document not found in cache after CORE ingestion."