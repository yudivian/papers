import os
import shutil
import tempfile
import pytest
import logging
from unittest.mock import patch
from beaver import BeaverDB

from papers.backend.tasks import ingest_paper
from papers.backend.models import KnowledgeBase, DownloadStatus
from papers.backend.config import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s", force=True)

@pytest.fixture
def live_env():
    """
    Provisions a temporary environment for live external network operations.
    """
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "live.db")
    storage_path = os.path.join(temp_dir, "real_pdfs")
    os.makedirs(storage_path)
    
    yield {
        "db_path": db_path,
        "storage_path": storage_path,
        "temp_dir": temp_dir
    }
    
    shutil.rmtree(temp_dir)

@pytest.mark.parametrize("real_doi", [
    "10.48550/arxiv.1706.03762",   # Attention Is All You Need (ArXiv)
    "10.48550/arxiv.1512.03385",   # Deep Residual Learning - ResNet (ArXiv)
    "10.1371/journal.pone.0115069" # Standard PLOS One DOI
])
def test_live_network_ingestion_flow(live_env, real_doi):
    """
    Verifies document acquisition against multiple live academic repositories.
    
    Ensures that the pipeline can robustly extract and validate PDFs across 
    different publishers, varying HTML structures, and dynamic fallback routes.
    """
    test_db = BeaverDB(live_env["db_path"])
    user_id = "real_world_tester"
    kb_id = f"kb_{user_id}"
    ticket_id = f"live_ticket_{real_doi.replace('/', '_')}"
    
    kbs_db = test_db.dict("knowledge_bases")
    kbs_db[kb_id] = KnowledgeBase(
        kb_id=kb_id, owner_id=user_id, name="Live KB"
    ).model_dump(mode="json")

    downloads_db = test_db.dict("downloads")
    downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}

    real_settings = Settings.load_from_yaml()
    real_settings.storage.local.base_path = live_env["storage_path"]
    real_settings.database.file = live_env["db_path"]
    real_settings.data_sources.priority = ["openalex"]

    with patch("papers.backend.tasks.get_task_infrastructure", return_value=(real_settings, test_db)):

        result = ingest_paper.callable(ticket_id, real_doi, user_id, kb_id)

        error_msg = downloads_db[ticket_id].get("error_message", "No database tracking error recorded")
        assert result is True, f"Live ingestion failed for {real_doi}! Trace: {error_msg}"
        
        docs_db = test_db.dict("global_documents")
        assert real_doi in docs_db
        assert len(docs_db[real_doi]["title"]) > 0
        
        expected_path = os.path.join(live_env["storage_path"], f"{real_doi.replace('/', '_')}.pdf")
        assert os.path.exists(expected_path)

        with open(expected_path, "rb") as f:
            header_chunk = f.read(2048)
            assert b"%PDF" in header_chunk