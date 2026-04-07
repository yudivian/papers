import pytest
from fastapi.testclient import TestClient
from papers.backend.main import app

@pytest.fixture(scope="session")
def live_app_client():
    """
    Enciende FastAPI y el worker de Castor UNA SOLA VEZ 
    al principio de la suite, y lo apaga al final de todos los tests.
    """
    with TestClient(app) as client:
        yield client