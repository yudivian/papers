import os
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

# Assuming your main FastAPI app is instantiated in main.py or api.py
# Adjust the import path 'papers.backend.main' if your app object lives elsewhere
from papers.backend.main import app 
from papers.backend.deps import get_current_user, get_db, get_settings
from papers.backend.config import Settings, OrcidConfig
from beaver import BeaverDB

# ==========================================
# Test Environment Setup
# ==========================================

# We define a temporary path for the BeaverDB instance used during tests
# to avoid modifying the actual development or production database.
TEST_DB_PATH = "./test_beaver_db"

def override_get_current_user():
    """Simulates an authenticated user for the API endpoints."""
    return "test_integration_user_001"

def override_get_settings():
    """Provides a valid configuration, ensuring ORCID is enabled."""
    return Settings.model_construct(
        orcid=OrcidConfig(enabled=True, base_url="https://orcid.org")
    )

def override_get_db():
    """
    Yields a real, functional BeaverDB instance pointing to a temporary path.
    """
    db = BeaverDB(TEST_DB_PATH)
    try:
        yield db
    finally:
        pass

@pytest.fixture(scope="function", autouse=True)
def setup_teardown_db():
    """
    Function-scoped fixture to ensure the test database environment is clean 
    before starting EVERY test and is removed after.
    Uses explicit .clear() to bypass in-memory caching from BeaverDB.
    """
    db = BeaverDB(TEST_DB_PATH)
    db.dict("orcid_status").clear()
    
    yield 
    
    db.dict("orcid_status").clear()
    
    if os.path.exists(TEST_DB_PATH):
        import shutil
        shutil.rmtree(TEST_DB_PATH, ignore_errors=True)

@pytest.fixture
def client():
    """
    Yields a TestClient with dependencies overridden to use the real 
    but isolated test environment.
    """
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client
        
    app.dependency_overrides.clear()


# ==========================================
# Live API Integration Tests
# ==========================================

def test_api_get_settings_empty(client):
    """
    Verify that querying settings for a new user returns the default empty payload.
    """
    response = client.get("/api/v1/orcid/settings")
    assert response.status_code == 200
    
    data = response.json()
    assert data["has_orcid"] is False
    assert data["orcid_id"] == ""
    assert data["is_enabled"] is False

def test_api_save_settings_new_orcid(client):
    """
    Verify that posting a real ORCID ID correctly triggers the live fetch,
    validates the data, and persists it into the real BeaverDB instance.
    """
    target_orcid = "0000-0002-2345-1387"
    payload = {
        "orcid_id": target_orcid,
        "is_enabled": True
    }
    
    response = client.post("/api/v1/orcid/settings", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    # ✅ Corregido para coincidir con el mensaje del router
    assert "saved" in data["message"].lower()

def test_api_save_settings_update_toggle_only(client):
    """
    Verify that updating the 'is_enabled' flag on an existing ORCID ID
    does not fail and successfully updates the state.
    """
    target_orcid = "0000-0002-2345-1387"
    payload = {
        "orcid_id": target_orcid,
        "is_enabled": False # Disabling it
    }
    
    response = client.post("/api/v1/orcid/settings", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"

def test_api_get_profile_forbidden(client):
    """
    Verify that requesting the profile when the integration is disabled 
    returns a 403 HTTP error.
    """
    target_orcid = "0000-0002-2345-1387"
    client.post("/api/v1/orcid/settings", json={"orcid_id": target_orcid, "is_enabled": False})
    
    response = client.get("/api/v1/orcid/profile")
    
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()

def test_api_get_profile_cached_data(client):
    """
    Verify that the GET profile endpoint correctly returns the locally 
    cached data without forcing a network request.
    """
    target_orcid = "0000-0002-2345-1387"
    
    # Re-enable the integration first (this automatically caches the data initially)
    client.post("/api/v1/orcid/settings", json={"orcid_id": target_orcid, "is_enabled": True})
    
    # Fetch the profile (should read from BeaverDB)
    response = client.get("/api/v1/orcid/profile")
    
    assert response.status_code == 200
    data = response.json()
    
    # Assert it returns the cached status
    assert data["sync_status"] == "cached"
    assert data["orcid_id"] == target_orcid
    assert "Yudivián" in data["full_name"]

def test_api_sync_profile_live_data(client):
    """
    Verify that the POST sync endpoint correctly forces a network fetch,
    updates BeaverDB, and returns the 'updated' status.
    """
    target_orcid = "0000-0002-2345-1387"
    
    # Ensure it's enabled
    client.post("/api/v1/orcid/settings", json={"orcid_id": target_orcid, "is_enabled": True})
    
    # Force the synchronization
    response = client.post("/api/v1/orcid/sync")
    
    assert response.status_code == 200
    data = response.json()
    
    # Assert structural integrity and the new 'updated' status
    assert data["sync_status"] == "updated"
    assert data["orcid_id"] == target_orcid
    assert isinstance(data["works"], list)
    
    # Verify at least one work has external IDs (like a DOI)
    has_external_id = False
    for work in data["works"]:
        if len(work.get("external_ids", [])) > 0:
            has_external_id = True
            break
            
    assert has_external_id, "Expected at least one work to contain external IDs."