import os
import shutil
import tempfile
import pytest
from unittest.mock import patch
from beaver import BeaverDB

from papers.backend.tasks import ingest_paper
from papers.backend.models import KnowledgeBase, DownloadStatus
from papers.backend.config import Settings

@pytest.fixture
def live_env():
    """
    Provisions a temporary, isolated environment for live network testing.
    """
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "live_papers.db")
    storage_path = os.path.join(temp_dir, "real_pdfs")
    os.makedirs(storage_path)
    
    yield {
        "db_path": db_path,
        "storage_path": storage_path,
        "temp_dir": temp_dir
    }
    
    shutil.rmtree(temp_dir)

def test_live_network_ingestion_flow(live_env):
    """
    Executes a real End-to-End ingestion using live external services.
    """
    test_db = BeaverDB(live_env["db_path"])
    user_id = "real_user"
    kb_id = f"kb_{user_id}"
    real_doi = "10.48550/arxiv.1706.03762" 
    ticket_id = "live_ticket_001"
    
    kbs_db = test_db.dict("knowledge_bases")
    kbs_db[kb_id] = KnowledgeBase(
        kb_id=kb_id, owner_id=user_id, name="Live KB"
    ).model_dump(mode="json")

    downloads_db = test_db.dict("downloads")
    downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}

    # Cargamos la configuración real para obtener las llaves válidas de config.yaml
    real_settings = Settings.load_from_yaml()

    with patch("papers.backend.tasks.db", test_db), \
         patch("papers.backend.tasks.settings") as mock_settings:

        mock_settings.storage.selected = "local"
        mock_settings.storage.local.base_path = live_env["storage_path"]
        mock_settings.data_sources.priority = ["openalex"]
        
        # [CORRECCIÓN APLICADA AQUÍ]
        mock_settings.data_sources.openalex.system_keys = real_settings.data_sources.openalex.system_keys
        mock_settings.data_sources.openalex.allow_system_fallback = True
        mock_settings.database.file = live_env["db_path"]

        # Pasamos ticket_id como primer argumento
        result = ingest_paper.callable(ticket_id, real_doi, user_id, kb_id)

        # Imprimir el error exacto si falla para no tener que adivinar
        if not result:
            error_msg = downloads_db[ticket_id].get('error_message', 'Error desconocido')
            print(f"\n[ERROR DEL WORKER] La descarga falló con el mensaje: {error_msg}")

        assert result is True

        docs_db = test_db.dict("global_documents")
        assert real_doi in docs_db
        
        saved_meta = docs_db[real_doi]
        assert "Attention" in saved_meta["title"]
        assert saved_meta["file_size"] > 100000 
        assert saved_meta["storage_uri"].startswith(live_env["storage_path"])

        expected_filename = f"{real_doi.replace('/', '_')}.pdf"
        pdf_path = os.path.join(live_env["storage_path"], expected_filename)
        assert os.path.exists(pdf_path)

        with open(pdf_path, "rb") as f:
            magic_bytes = f.read(4)
            assert magic_bytes == b"%PDF"

        updated_kb = kbs_db[kb_id]
        assert real_doi in updated_kb["document_ids"]
        
        assert downloads_db[ticket_id]["status"] == DownloadStatus.COMPLETED.value