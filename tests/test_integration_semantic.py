import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from beaver import BeaverDB

from papers.backend.tasks import _async_ingest
from papers.backend.data_sources import get_data_source
from papers.backend.models import GlobalDocumentMeta, DownloadStatus

@pytest.fixture
def integration_env():
    """
    Provisions a temporary, isolated environment for data (DB and PDFs).
    Uses the host's global AI model cache for a realistic integration test.
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
    Performs a real End-to-End integration test.
    
    Validates the entire flow:
    1. Ingestion of metadata through the prioritized pipeline.
    2. Real-world vectorization using the SemanticEngine singleton.
    3. Persistence of vectors in BeaverDB's 'semantic_vectors' collection.
    4. Retrieval via BeaverCacheSource using contextual semantic similarity.
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
            abstract="We propose a new network architecture based solely on attention mechanisms, dispensing with recurrence and convolutions.",
            keywords=["Machine Learning", "NLP", "Transformers"]
        ),
        "10.000/med": GlobalDocumentMeta(
            doi="10.000/med", 
            title="Efficacy of Aspirin in Cardiology", 
            year=2020, 
            file_size=0, 
            storage_uri="http://fake.url/2",
            abstract="This clinical trial evaluates the daily intake of aspirin for preventing heart attacks.",
            keywords=["Medicine", "Cardiology", "Clinical Trial"]
        )
    }

    async def mock_fetch(self, doi):
        return papers_data.get(doi)
        
    async def mock_download(*args, **kwargs):
        return b"%PDF-1.4 Fake Data"

    from papers.backend.tasks import settings as tasks_settings
    
    old_db_path = tasks_settings.database.file
    old_storage_path = tasks_settings.storage.local.base_path
    
    tasks_settings.database.file = integration_env["db_path"]
    tasks_settings.storage.local.base_path = integration_env["storage_path"]

    with patch("papers.backend.tasks.db", test_db), \
         patch("papers.backend.data_sources.OpenAlexSource.fetch_by_doi", mock_fetch), \
         patch("papers.backend.tasks._download_asset", mock_download):

        for i, doi in enumerate(papers_data.keys()):
            ticket_id = f"ticket_{i}"
            downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}
            
            success = await _async_ingest(ticket_id, doi, user_id, kb_id)
            
            error = downloads_db[ticket_id].get("error_message", "No error message recorded")
            assert success is True, f"Ingestion failed for {doi}. Reason: {error}"

    tasks_settings.database.file = old_db_path
    tasks_settings.storage.local.base_path = old_storage_path

    vectors_db = test_db.dict("semantic_vectors")
    assert len(vectors_db) == 2, "Semantic vectors were not saved."
    
    cache_source = get_data_source(
        "cache", 
        settings=tasks_settings,
        db=test_db
    )
    
    results = await cache_source.search_by_text("cardiovascular medical treatments", limit=1)
    
    assert len(results) > 0, "Semantic search returned empty."
    assert results[0].doi == "10.000/med"
    assert results[0].source == "cache"