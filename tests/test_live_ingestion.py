import os
import pytest
import logging
from unittest.mock import patch
from beaver import BeaverDB
from papers.backend.tasks import ingest_paper
from papers.backend.models import KnowledgeBase, DownloadStatus
from papers.backend.config import Settings
from papers.backend import deps

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s", force=True)

@pytest.fixture
def sys_settings(tmp_path):
    """
    Hybrid strategy: Loads real config for network access but isolates
    database and storage paths to a temporary directory.
    """
    settings = Settings.load_from_yaml()
    settings.database.file = str(tmp_path / "test_ingestion.db")
    settings.storage.selected = "local"
    settings.storage.local.base_path = str(tmp_path / "storage_ingestion")
    
    deps._global_db = None
    with patch("papers.backend.config.Settings.load_from_yaml", return_value=settings):
        yield settings
    deps._global_db = None


@pytest.fixture
def db_context(sys_settings):
    """
    Provides a fresh, isolated BeaverDB instance.
    """
    return BeaverDB(sys_settings.database.file)
            
@pytest.mark.parametrize("real_doi", [
    "10.48550/arxiv.1706.03762",   # OpenAlex (ArXiv)
    "core:4190558",                # CORE: Query-biased summaries
    "core:82830889",               # CORE: Deep Learning studies
    "10.1371/journal.pone.0115069" # Standard DOI
])
def test_live_network_ingestion_flow(db_context, sys_settings, real_doi):
    """
    Validates live network resolution and PDF acquisition for both OpenAlex and CORE.
    """
    test_db = db_context
    user_id = "live_tester"
    kb_id = f"kb_{user_id}"
    ticket_id = f"ticket_{real_doi.replace(':', '_').replace('/', '_')}"
    
    kbs_db = test_db.dict("knowledge_bases")
    kbs_db[kb_id] = KnowledgeBase(kb_id=kb_id, owner_id=user_id, name="Live").model_dump(mode="json")
    
    downloads_db = test_db.dict("downloads")
    downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}

    if real_doi.startswith("core:"):
        sys_settings.data_sources.priority = ["core"]
    else:
        sys_settings.data_sources.priority = ["openalex"]

    with patch("papers.backend.tasks.get_task_infrastructure", return_value=(sys_settings, test_db)):
        result = ingest_paper.callable(ticket_id, real_doi, user_id, kb_id)
        
        # Validation
        assert result is True, f"Failed live ingestion for {real_doi}"
        
        docs_db = test_db.dict("global_documents")
        assert real_doi in docs_db
        
        # Verify file existence on disk
        doc_meta = docs_db[real_doi]
        storage_path = sys_settings.storage.local.base_path
        file_name = f"{doc_meta['doi'].replace('/', '_').replace(':', '_')}.pdf"
        file_path = os.path.join(storage_path, file_name)
        
        assert os.path.exists(file_path), f"Downloaded file not found at {file_path}"