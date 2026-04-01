"""
Integration test suite for the primary FastAPI application router.

This module validates the integration between HTTP endpoints and the underlying 
BeaverDB storage layer. It employs dependency overrides to bypass authentication, 
isolate the database state, and mock application configurations.
"""
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from beaver import BeaverDB

from papers.backend.main import app
from papers.backend.deps import get_db, get_current_user, get_settings
from papers.backend.models import DownloadStatus, GlobalDocumentMeta
from papers.backend.config import Settings

client = TestClient(app)

@pytest.fixture
def api_env(tmp_path):
    """
    Provisions an isolated testing environment with dependency overrides.
    """
    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "files"
    storage_path.mkdir()
    
    test_db = BeaverDB(str(db_path))

    test_settings = Settings.load_from_yaml()
    test_settings.storage.local.base_path = str(storage_path)

    app.dependency_overrides[get_db] = lambda: test_db
    app.dependency_overrides[get_current_user] = lambda: "authorized_test_user"
    app.dependency_overrides[get_settings] = lambda: test_settings

    yield {
        "db": test_db,
        "storage_path": str(storage_path)
    }

    app.dependency_overrides.clear()

def test_kbs_transfer_and_security(api_env):
    """
    Validates document transfers and ownership-based access control.
    """
    db = api_env["db"]
    kbs_db = db.dict("knowledge_bases")

    source_response = client.post("/api/v1/kbs", json={"name": "Source", "description": ""})
    source_kb_id = source_response.json()["kb_id"]
    
    dest_response = client.post("/api/v1/kbs", json={"name": "Dest", "description": ""})
    dest_kb_id = dest_response.json()["kb_id"]

    kb_obj = kbs_db[source_kb_id]
    kb_obj["document_ids"] = ["10.test/auth"]
    kbs_db[source_kb_id] = kb_obj

    client.post(f"/api/v1/kbs/{dest_kb_id}/transfer", json={"dois": ["10.test/auth"], "source_kb_id": source_kb_id})
    
    assert "10.test/auth" in kbs_db[dest_kb_id]["document_ids"]

    app.dependency_overrides[get_current_user] = lambda: "intruder"
    assert client.get(f"/api/v1/kbs/{source_kb_id}").status_code == 403

def test_documents_deep_cleanup(api_env):
    """
    Evaluates referential integrity during bulk document purging.
    """
    db = api_env["db"]
    storage = api_env["storage_path"]
    
    linked_file = os.path.join(storage, "linked.dat")
    unlinked_file = os.path.join(storage, "unlinked.dat")
    
    with open(linked_file, 'w') as f: f.write("content")
    with open(unlinked_file, 'w') as f: f.write("content")

    docs_db = db.dict("global_documents")
    docs_db["10.test/linked"] = {"doi": "10.test/linked", "title": "L", "year": 2024, "file_size": 7, "storage_uri": linked_file, "mime_type": "application/octet-stream"}
    docs_db["10.test/unlinked"] = {"doi": "10.test/unlinked", "title": "U", "year": 2024, "file_size": 7, "storage_uri": unlinked_file, "mime_type": "application/octet-stream"}

    kb_res = client.post("/api/v1/kbs", json={"name": "P", "description": ""})
    kbs_db = db.dict("knowledge_bases")
    kb_obj = kbs_db[kb_res.json()["kb_id"]]
    kb_obj["document_ids"] = ["10.test/linked"]
    kbs_db[kb_res.json()["kb_id"]] = kb_obj

    client.post("/api/v1/documents/cleanup", json={"unlinked_only": True})
    
    assert "10.test/linked" in docs_db
    assert "10.test/unlinked" not in docs_db
    assert not os.path.exists(unlinked_file)

@patch("papers.backend.routers.discovery.DiscoveryOrchestrator")
def test_discovery_fallback_logic(MockOrch, api_env):
    """
    Verifies the orchestrator-driven resolution strategy.
    """
    orch_instance = MockOrch.return_value
    
    async def mock_resolve(doi):
        if doi == "10.test/hit":
            return GlobalDocumentMeta(doi=doi, title="Hit", year=2024, file_size=0, storage_uri="")
        return None
        
    orch_instance.resolve_doi = AsyncMock(side_effect=mock_resolve)

    response = client.get("/api/v1/discovery/doi/10.test/hit")
    assert response.status_code == 200
    assert response.json()["title"] == "Hit"

    assert client.get("/api/v1/discovery/doi/10.test/miss").status_code == 404

def test_health_and_users_real_quota(api_env):
    """
    Validates dynamic quota calculation from the filesystem.
    """
    db = api_env["db"]
    storage = api_env["storage_path"]
    
    test_file = os.path.join(storage, "quota.dat")
    with open(test_file, 'wb') as f: f.write(b"DATA")
        
    docs_db = db.dict("global_documents")
    docs_db["10.test/q"] = {"doi": "10.test/q", "title": "Q", "year": 2024, "file_size": 4, "storage_uri": test_file, "mime_type": "application/octet-stream"}

    profile = client.get("/api/v1/users/me").json()
    assert profile["quota"]["used_bytes"] == 4

@patch("papers.backend.routers.ingestion.ingest_paper")
def test_ingestion_async_flow(mock_ingest, api_env):
    """
    Verifies non-blocking task submission and tracking.
    """
    res = client.post("/api/v1/ingestion/start", json={"doi": "10.test/a", "kb_id": "kb_1"})
    ticket_id = res.json()["ticket_id"]
    
    mock_ingest.submit.assert_called_once()
    assert client.get(f"/api/v1/ingestion/status/{ticket_id}").status_code == 200

def test_documents_file_stream_and_delete(api_env):
    """
    Confirms format-agnostic physical asset delivery and purge consistency.
    """
    db = api_env["db"]
    storage = api_env["storage_path"]
    path = os.path.join(storage, "s.epub")
    with open(path, 'wb') as f: f.write(b"EPUB DATA")
        
    db.dict("global_documents")["10.test/s"] = {
        "doi": "10.test/s", 
        "title": "S", 
        "year": 2024, 
        "file_size": 9, 
        "storage_uri": path,
        "mime_type": "application/epub+zip"
    }

    assert client.get("/api/v1/documents/10.test/s/file").status_code == 200
    client.delete("/api/v1/documents/10.test/s")
    assert not os.path.exists(path)

@patch("papers.backend.routers.discovery.DiscoveryOrchestrator")
def test_semantic_search_endpoint(MockOrch, api_env):
    """
    Validates that the search endpoint returns a dictionary mapped by source.
    """
    orch_instance = MockOrch.return_value
    mock_meta = GlobalDocumentMeta(
        doi="10.test/semantic", title="Hit", year=2024, 
        file_size=0, storage_uri=""
    )
    
    orch_instance.search = AsyncMock(return_value={"cache": [mock_meta]})

    response = client.get("/api/v1/discovery/search?q=test&limit=5")
    assert response.status_code == 200
    data = response.json()
    
    assert isinstance(data, dict)
    assert "cache" in data
    assert data["cache"][0]["doi"] == "10.test/semantic"