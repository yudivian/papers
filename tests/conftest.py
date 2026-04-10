import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from papers.backend.main import app
from papers.backend import deps


@pytest.fixture
def mock_global_settings(tmp_path: Path) -> MagicMock:
    """
    Creates and configures an isolated, in-memory mock of the application Settings.
    
    This fixture prevents the application from loading the physical config.yaml file
    from the local environment. It configures the database and storage paths to point
    to temporary directories managed by pytest, ensuring complete data isolation.
    Default quotas and initial knowledge base parameters are populated to satisfy
    the application's startup validation requirements.
    """
    mock_settings = MagicMock()
    
    db_file = tmp_path / "test_beaver.db"
    mock_settings.database.file = str(db_file)
    
    storage_dir = tmp_path / "test_storage"
    storage_dir.mkdir(exist_ok=True)
    mock_settings.storage.selected = "local"
    mock_settings.storage.local.path = str(storage_dir)
    
    mock_settings.app.initial_kb_name = "Test KB"
    mock_settings.app.initial_kb_description = "KB for testing"
    mock_settings.quotas.user_logical_limit_gb = 1
    
    return mock_settings


@pytest.fixture
def live_app_client(mock_global_settings: MagicMock):
    """
    Provides a safe, isolated FastAPI TestClient with patched dependencies.
    
    This fixture resets the global database singleton to prevent state leakage 
    between tests. It intercepts any internal calls to Settings.load_from_yaml 
    using unittest.mock.patch, forcing the application to consume the isolated 
    mock_global_settings. Additionally, it applies FastAPI dependency overrides 
    for robust isolation. All overrides and singletons are explicitly cleared 
    during the generator teardown.
    """
    deps._global_db = None
    
    with patch("papers.backend.config.Settings.load_from_yaml", return_value=mock_global_settings):
        app.dependency_overrides[deps.get_settings] = lambda: mock_global_settings
        
        with TestClient(app) as client:
            yield client
            
        app.dependency_overrides.clear()
        deps._global_db = None