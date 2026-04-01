import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from beaver import BeaverDB

from papers.backend.tasks import _async_ingest
from papers.backend.data_sources import get_data_source
from papers.backend.models import GlobalDocumentMeta, DownloadStatus
from papers.backend.config import Settings

@pytest.fixture
def integration_env():
    """
    Provisions a temporary, isolated environment for metadata and assets.
    """
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "integration.db")
    storage_path = os.path.join(temp_dir, "pdfs")
    os.makedirs(storage_path)
    
    yield {
        "db_path": db_path,
        "storage_path": storage_path,
        "temp_dir": temp_dir
    }
    
    shutil.rmtree(temp_dir)

@pytest.mark.anyio
async def test_full_semantic_pipeline(integration_env):
    """
    Performs an end-to-end integration test of the semantic indexing pipeline.

    Workflow:
    1. Mocks the metadata resolution and binary download phases.
    2. Executes the core ingestion logic.
    3. Verifies that high-dimensional vectors are stored in the test database.
    4. Confirms that semantic similarity search returns the expected documents.
    """
    test_db = BeaverDB(integration_env["db_path"])
    user_id = "integration_user"
    kb_id = f"kb_{user_id}"
    
    kbs_db = test_db.dict("knowledge_bases")
    downloads_db = test_db.dict("downloads")
    
    kbs_db[kb_id] = {"kb_id": kb_id, "owner_id": user_id, "name": "Test KB", "document_ids": []}
    
    papers_data = {
        "10.000/ai": GlobalDocumentMeta(
            doi="10.000/ai", 
            title="Attention Is All You Need", 
            year=2017, 
            file_size=0, 
            storage_uri="http://fake.url/1",
            abstract="Network architecture based solely on attention mechanisms.",
            keywords=["Transformers"]
        ),
        "10.000/med": GlobalDocumentMeta(
            doi="10.000/med", 
            title="Efficacy of Aspirin in Cardiology", 
            year=2020, 
            file_size=0, 
            storage_uri="http://fake.url/2",
            abstract="Clinical trial evaluating aspirin for preventing heart attacks.",
            keywords=["Medicine"]
        )
    }

    async def mock_fetch(self, doi):
        return papers_data.get(doi)
        
    async def mock_download(*args, **kwargs):
        return b"%PDF-1.4 Fake Data"

    test_settings = Settings.load_from_yaml()
    test_settings.database.file = integration_env["db_path"]
    test_settings.storage.local.base_path = integration_env["storage_path"]

    with patch("papers.backend.tasks.get_task_infrastructure", return_value=(test_settings, test_db)), \
         patch("papers.backend.data_sources.OpenAlexSource.fetch_by_doi", mock_fetch), \
         patch("papers.backend.tasks._download_asset", mock_download):

        for i, doi in enumerate(papers_data.keys()):
            ticket_id = f"ticket_{i}"
            downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}
            
            success = await _async_ingest(ticket_id, doi, user_id, kb_id)
            
            error = downloads_db[ticket_id].get("error_message", "No error message recorded")
            assert success is True, f"Ingestion failed for {doi}. Reason: {error}"

    vectors_db = test_db.dict("semantic_vectors")
    assert len(vectors_db) == 2, "Semantic vectors were not saved."
    
    cache_source = get_data_source(
        "cache", 
        settings=test_settings,
        db=test_db
    )
    
    results = await cache_source.search_by_text("medical treatments", limit=1)
    
    assert len(results) > 0, "Semantic search returned empty."
    assert results[0].doi == "10.000/med"
    assert results[0].source == "cache"