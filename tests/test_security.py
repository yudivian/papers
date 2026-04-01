import os
import tempfile
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from beaver import BeaverDB

from papers.backend.security import get_current_user, get_settings, get_db
from papers.backend.config import Settings, QuotasConfig
from papers.backend.models import User

@pytest.fixture(scope="module")
def temp_db_path():
    """
    Provide an isolated temporary file path for the BeaverDB instance.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.remove(path)

@pytest.fixture(scope="module")
def mock_settings():
    """
    Provide a controlled Settings object to avoid relying on physical YAML files.
    """
    return Settings(
        app={
            "environment": "testing", 
            "log_level": "DEBUG", 
            "server": {"host": "localhost", "port": 8000},
            "initial_kb_name": "Test Library",
            "initial_kb_description": "Mocked Description"
        },
        database={"file": "test.db"},
        storage={"selected": "local", "local": {"base_path": "/tmp"}},
        data_sources={"priority": ["cache"], "openalex": {"system_keys": ["test_key"]}},
        quotas={"user_logical_limit_gb": 2, "max_concurrent_tasks": 1},
        search={"model_name": "test-model"}
    )

@pytest.fixture(scope="module")
def test_app(temp_db_path, mock_settings):
    """
    Construct a minimalist FastAPI application with overridden dependencies 
    to isolate the security logic.
    """
    app = FastAPI()
    db_instance = BeaverDB(temp_db_path)

    def override_get_settings():
        return mock_settings

    def override_get_db():
        return db_instance

    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_db] = override_get_db

    @app.get("/test-auth", response_model=User)
    async def auth_endpoint(user: User = Depends(get_current_user)):
        return user

    return app

@pytest.fixture(scope="module")
def client(test_app):
    """
    Provide the synchronous TestClient for the overridden FastAPI app.
    """
    return TestClient(test_app)

def test_jit_provisioning_creates_new_user_and_kb(client, temp_db_path, mock_settings):
    """
    Verify that providing an unknown X-User-ID triggers the JIT provisioning 
    sequence, persisting both the User and the default Knowledge Base in BeaverDB.
    """
    test_user_id = "researcher_999"
    response = client.get("/test-auth", headers={"X-User-ID": test_user_id})
    
    assert response.status_code == 200
    
    db = BeaverDB(temp_db_path)
    kbs_db = db.dict("knowledge_bases")
    kb_id = f"default-{test_user_id}"
    
    assert kbs_db[kb_id]["name"] == "Test Library"
    assert kbs_db[kb_id]["description"] == "Mocked Description"

def test_existing_user_retrieval_bypasses_creation(client, temp_db_path):
    """
    Verify that subsequent requests with a known X-User-ID retrieve the existing 
    User record from BeaverDB without resetting quotas or duplicating data.
    """
    test_user_id = "researcher_retrieval"
    
    client.get("/test-auth", headers={"X-User-ID": test_user_id})
    
    db = BeaverDB(temp_db_path)
    users_db = db.dict("users")
    
    user_data = users_db[test_user_id]
    user_data["used_bytes"] = 500
    users_db[test_user_id] = user_data
    
    response = client.get("/test-auth", headers={"X-User-ID": test_user_id})
    
    assert response.status_code == 200
    
    response_data = response.json()
    assert response_data["user_id"] == test_user_id
    assert response_data["used_bytes"] == 500