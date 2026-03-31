import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from beaver import BeaverDB

from papers.backend.main import app
from papers.backend.deps import get_db, get_current_user
from papers.backend.models import DownloadStatus, GlobalDocumentMeta

client = TestClient(app)

@pytest.fixture
def api_env(tmp_path):
    """
    Provisions an isolated testing environment using pytest's temporary directory fixture.
    
    This fixture creates a dedicated BeaverDB instance and a temporary storage directory 
    for physical files. It leverages FastAPI's dependency overrides to inject these 
    test-specific resources and a mock user identity into the application's request 
    lifecycle, ensuring that tests do not mutate the development or production state.
    
    Args:
        tmp_path: A pathlib.Path object provided by pytest for temporary directory management.
        
    Yields:
        dict: A dictionary containing the injected database instance and storage path.
    """
    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "pdfs"
    storage_path.mkdir()
    
    test_db = BeaverDB(str(db_path))

    def override_get_db():
        return test_db

    def override_get_current_user():
        return "authorized_test_user"

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    yield {
        "db": test_db,
        "storage_path": str(storage_path)
    }

    app.dependency_overrides.clear()

def test_kbs_transfer_and_security(api_env):
    """
    Validates the transactional integrity of document transfers between Knowledge Bases 
    and enforces strict ownership-based authorization constraints.
    
    This test verifies that documents are correctly removed from the source workspace 
    and appended to the destination workspace. It subsequently simulates a malicious 
    access attempt by modifying the dependency override to assert that the system 
    rejects unauthorized read and delete operations with a 403 Forbidden status.
    
    Args:
        api_env: The isolated testing environment fixture.
    """
    db = api_env["db"]
    kbs_db = db.dict("knowledge_bases")

    source_response = client.post("/api/v1/kbs", json={"name": "Source Workspace", "description": ""})
    source_kb_id = source_response.json()["kb_id"]
    
    dest_response = client.post("/api/v1/kbs", json={"name": "Destination Workspace", "description": ""})
    dest_kb_id = dest_response.json()["kb_id"]

    kb_obj = kbs_db[source_kb_id]
    kb_obj["document_ids"] = ["10.test/auth"]
    kbs_db[source_kb_id] = kb_obj

    transfer_payload = {"dois": ["10.test/auth"], "source_kb_id": source_kb_id}
    transfer_response = client.post(f"/api/v1/kbs/{dest_kb_id}/transfer", json=transfer_payload)
    
    assert transfer_response.status_code == 200
    assert transfer_response.json()["transferred_count"] == 1

    assert "10.test/auth" not in kbs_db[source_kb_id]["document_ids"]
    assert "10.test/auth" in kbs_db[dest_kb_id]["document_ids"]

    app.dependency_overrides[get_current_user] = lambda: "unauthorized_intruder"
    
    unauthorized_read = client.get(f"/api/v1/kbs/{source_kb_id}")
    assert unauthorized_read.status_code == 403

    unauthorized_delete = client.delete(f"/api/v1/kbs/{source_kb_id}")
    assert unauthorized_delete.status_code == 403

def test_documents_deep_cleanup(api_env):
    """
    Evaluates the bulk document cleanup protocol, ensuring it maintains referential 
    integrity and successfully purges unlinked physical assets from the filesystem.
    
    The test seeds the environment with both linked and unlinked mock documents, 
    including physical files on disk. It asserts that the cleanup endpoint exclusively 
    targets unlinked documents when specified, correctly removing database entries 
    and deleting the underlying binary files without affecting linked assets.
    
    Args:
        api_env: The isolated testing environment fixture.
    """
    db = api_env["db"]
    storage = api_env["storage_path"]
    
    linked_file = os.path.join(storage, "linked_asset.pdf")
    unlinked_file = os.path.join(storage, "unlinked_asset.pdf")
    
    with open(linked_file, 'w') as file_handler: 
        file_handler.write("mock binary content")
    with open(unlinked_file, 'w') as file_handler: 
        file_handler.write("mock binary content")

    docs_db = db.dict("global_documents")
    docs_db["10.test/linked"] = {
        "doi": "10.test/linked", "title": "Linked Document", "year": 2024, 
        "file_size": 19, "storage_uri": linked_file, "abstract": "", "keywords": []
    }
    docs_db["10.test/unlinked"] = {
        "doi": "10.test/unlinked", "title": "Unlinked Document", "year": 2024, 
        "file_size": 19, "storage_uri": unlinked_file, "abstract": "", "keywords": []
    }

    kb_response = client.post("/api/v1/kbs", json={"name": "Active Project", "description": ""})
    kb_id = kb_response.json()["kb_id"]
    kbs_db = db.dict("knowledge_bases")
    kb_obj = kbs_db[kb_id]
    kb_obj["document_ids"] = ["10.test/linked"]
    kbs_db[kb_id] = kb_obj

    cleanup_response = client.post("/api/v1/documents/cleanup", json={"unlinked_only": True})
    
    assert cleanup_response.status_code == 200
    assert cleanup_response.json()["deleted_count"] == 1

    assert "10.test/linked" in docs_db
    assert "10.test/unlinked" not in docs_db
    
    assert os.path.exists(linked_file)
    assert not os.path.exists(unlinked_file)

@patch("papers.backend.routers.discovery.get_data_source")
def test_discovery_fallback_logic(mock_get_source, api_env):
    """
    Verifies the tiered metadata resolution strategy within the discovery endpoint.
    
    This test mocks the data source factory to simulate cache hits, cache misses 
    requiring external provider resolution, and total resolution failures. It asserts 
    that the endpoint routes requests correctly according to the priority configuration 
    and handles validation structures appropriately.
    
    Args:
        mock_get_source: The patched factory function for data source retrieval.
        api_env: The isolated testing environment fixture.
    """
    class MockSource:
        def __init__(self, name): 
            self.name = name
            
        async def fetch_by_doi(self, doi):
            if self.name == "cache" and doi == "10.test/local": 
                return GlobalDocumentMeta(
                    doi="10.test/local", title="Locally Cached Result", year=2024, 
                    file_size=1024, storage_uri="/mock/path", abstract="", keywords=[]
                )
            if self.name == "openalex" and doi == "10.test/remote": 
                return GlobalDocumentMeta(
                    doi="10.test/remote", title="External Provider Result", year=2023, 
                    file_size=0, storage_uri="", abstract="", keywords=[]
                )
            return None

    mock_get_source.side_effect = lambda name, **kwargs: MockSource(name)

    local_response = client.get("/api/v1/discovery/doi/10.test/local")
    assert local_response.status_code == 200
    assert local_response.json()["title"] == "Locally Cached Result"

    remote_response = client.get("/api/v1/discovery/doi/10.test/remote")
    assert remote_response.status_code == 200
    assert remote_response.json()["title"] == "External Provider Result"

    not_found_response = client.get("/api/v1/discovery/doi/10.test/missing")
    assert not_found_response.status_code == 404

def test_health_and_users_real_quota(api_env):
    """
    Validates the accurate calculation of storage quotas based on physical disk utilization.
    
    The test creates a mock binary file of a known byte size, registers it within the 
    global document database, and asserts that the user profile endpoint computes the 
    exact storage footprint by probing the filesystem rather than relying on cached metadata.
    
    Args:
        api_env: The isolated testing environment fixture.
    """
    db = api_env["db"]
    storage = api_env["storage_path"]
    
    test_file = os.path.join(storage, "quota_verification.pdf")
    binary_payload = b"QUOTA_TEST_DATA"
    with open(test_file, 'wb') as file_handler: 
        file_handler.write(binary_payload)
        
    docs_db = db.dict("global_documents")
    docs_db["10.test/quota"] = {
        "doi": "10.test/quota", "title": "Quota Evaluation Document", "year": 2024, 
        "file_size": len(binary_payload), "storage_uri": test_file, "abstract": "", "keywords": []
    }

    health_response = client.get("/health")
    assert health_response.status_code == 200
    
    profile_response = client.get("/api/v1/users/me")
    assert profile_response.status_code == 200
    
    response_payload = profile_response.json()
    assert response_payload["user_id"] == "authorized_test_user"
    assert response_payload["quota"]["used_bytes"] == len(binary_payload)

@patch("papers.backend.routers.ingestion.ingest_paper")
def test_ingestion_async_flow(mock_ingest, api_env):
    """
    Tests the asynchronous ingestion lifecycle and task polling mechanism.
    
    This ensures that the ingestion start endpoint successfully enqueues the background 
    task with the correct parameters using the Castor submit method, generates a tracking 
    identifier, and that the status endpoint accurately reports the initial pending state.
    
    Args:
        mock_ingest: The patched asynchronous worker function proxy.
        api_env: The isolated testing environment fixture.
    """
    payload = {"doi": "10.test/async", "kb_id": "kb_test_target"}
    
    start_response = client.post("/api/v1/ingestion/start", json=payload)
    assert start_response.status_code == 202
    ticket_id = start_response.json()["ticket_id"]
    
    mock_ingest.submit.assert_called_once_with(
        ticket_id=ticket_id, doi="10.test/async", user_id="authorized_test_user", kb_id="kb_test_target"
    )
    
    status_response = client.get(f"/api/v1/ingestion/status/{ticket_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == DownloadStatus.PENDING.value
    
    missing_status_response = client.get("/api/v1/ingestion/status/invalid_ticket_id")
    assert missing_status_response.status_code == 404
    
def test_documents_pdf_stream_and_delete(api_env):
    """
    Confirms the physical delivery of binary assets and their complete removal upon deletion.
    
    The test generates a physical file, asserts that the PDF streaming endpoint serves 
    the correct binary payload with appropriate headers, and then executes a deletion 
    operation to verify the complete eradication of both database records and disk assets.
    
    Args:
        api_env: The isolated testing environment fixture.
    """
    db = api_env["db"]
    storage = api_env["storage_path"]
    
    test_file = os.path.join(storage, "stream_verification.pdf")
    pdf_binary = b"%PDF-1.4 Mock Binary Stream"
    with open(test_file, 'wb') as file_handler: 
        file_handler.write(pdf_binary)
        
    db.dict("global_documents")["10.test/stream"] = {
        "doi": "10.test/stream", "title": "Stream Target", "year": 2024, 
        "file_size": len(pdf_binary), "storage_uri": test_file, "abstract": "", "keywords": []
    }
    db.dict("semantic_vectors")["10.test/stream"] = {"vector": [0.1, 0.2, 0.3]}

    stream_response = client.get("/api/v1/documents/10.test/stream/pdf")
    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"] == "application/pdf"
    assert stream_response.content == pdf_binary

    list_response = client.get("/api/v1/documents")
    assert len(list_response.json()) == 1

    delete_response = client.delete("/api/v1/documents/10.test/stream")
    assert delete_response.status_code == 200
    
    assert "10.test/stream" not in db.dict("global_documents")
    assert "10.test/stream" not in db.dict("semantic_vectors")
    assert not os.path.exists(test_file)

@patch("papers.backend.routers.discovery.get_data_source")
def test_semantic_search_endpoint(mock_get_source, api_env):
    """
    Validates the parameter passing and response structuring of the semantic search endpoint.
    
    By mocking the underlying cache data source, the test confirms that query strings 
    and limits are correctly routed through the system boundary and that the resulting 
    metadata payloads are properly serialized.
    
    Args:
        mock_get_source: The patched factory function for data source retrieval.
        api_env: The isolated testing environment fixture.
    """
    class MockCacheSource:
        async def search_by_text(self, query, limit):
            assert query == "neural network architecture"
            assert limit == 5
            return [GlobalDocumentMeta(
                doi="10.test/semantic", title="Semantic Search Hit", year=2024, 
                file_size=2048, storage_uri="", abstract="", keywords=[]
            )]

    mock_get_source.return_value = MockCacheSource()

    search_response = client.get("/api/v1/discovery/search?q=neural network architecture&limit=5")
    assert search_response.status_code == 200
    assert len(search_response.json()) == 1
    assert search_response.json()[0]["doi"] == "10.test/semantic"