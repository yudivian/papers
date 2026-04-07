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
    "10.48550/arxiv.1706.03762",   # OpenAlex (ArXiv)
    "core:4190558",                # CORE: Query-biased summaries
    "core:82830889",               # CORE: Deep Learning studies
    "10.1371/journal.pone.0115069" # Standard DOI
])
def test_live_network_ingestion_flow(live_env, real_doi):
    """
    Validates live network resolution and PDF acquisition for both OpenAlex and CORE.
    """
    test_db = BeaverDB(live_env["db_path"])
    user_id = "live_tester"
    kb_id = f"kb_{user_id}"
    ticket_id = f"ticket_{real_doi.replace(':', '_').replace('/', '_')}"
    
    # Pre-setup DB
    kbs_db = test_db.dict("knowledge_bases")
    kbs_db[kb_id] = KnowledgeBase(kb_id=kb_id, owner_id=user_id, name="Live").model_dump(mode="json")
    
    downloads_db = test_db.dict("downloads")
    downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}

    real_settings = Settings.load_from_yaml()
    real_settings.storage.local.base_path = live_env["storage_path"]
    real_settings.database.file = live_env["db_path"]
    
    # Important: Enable both or switch priority based on DOI prefix
    if real_doi.startswith("core:"):
        real_settings.data_sources.priority = ["core"]
    else:
        real_settings.data_sources.priority = ["openalex"]

    with patch("papers.backend.tasks.get_task_infrastructure", return_value=(real_settings, test_db)):
        result = ingest_paper.callable(ticket_id, real_doi, user_id, kb_id)
        
        # Validation
        assert result is True, f"Failed live ingestion for {real_doi}"
        
        docs_db = test_db.dict("global_documents")
        assert real_doi in docs_db
        
        # Verify file existence on disk
        doc_meta = docs_db[real_doi]
        file_path = os.path.join(live_env["storage_path"], f"{doc_meta['doi'].replace('/', '_').replace(':', '_')}.pdf")
        assert os.path.exists(file_path), f"PDF file not found at {file_path}"