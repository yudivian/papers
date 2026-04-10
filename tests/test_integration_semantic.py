import os
import pytest
from unittest.mock import patch, MagicMock
from beaver import BeaverDB

from papers.backend import deps
from papers.backend.tasks import _async_ingest
from papers.backend.data_sources import get_data_source
from papers.backend.models import GlobalDocumentMeta, DownloadStatus
from papers.backend.config import Settings

@pytest.fixture
def sys_settings(tmp_path):
    """
    Hybrid strategy: Isolates DB and Storage so SemanticEngine does not pollute production.
    """
    settings = Settings.load_from_yaml()
    settings.database.file = str(tmp_path / "test_integration_semantic.db")
    settings.storage.selected = "local"
    settings.storage.local.base_path = str(tmp_path / "storage_semantic")
    
    deps._global_db = None
    with patch("papers.backend.config.Settings.load_from_yaml", return_value=settings):
        yield settings
    deps._global_db = None

@pytest.fixture
def db_context(sys_settings):
    """Provides a fresh, isolated database for integration tests."""
    return BeaverDB(sys_settings.database.file)

@pytest.mark.anyio
async def test_full_semantic_pipeline(db_context, sys_settings):
    """
    Performs an end-to-end integration test of the semantic indexing pipeline.

    Workflow:
    1. Mocks the metadata resolution and binary download phases.
    2. Executes the core ingestion logic.
    3. Verifies that high-dimensional vectors are stored in the test database.
    4. Confirms that semantic similarity search returns the expected documents.
    """
    test_db = db_context
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
        
    async def mock_download(url, expected_mime):
        return b"%PDF-1.4 Fake Data", "application/pdf"

    with patch("papers.backend.tasks.get_task_infrastructure", return_value=(sys_settings, test_db)), \
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
        settings=sys_settings,
        db=test_db
    )
    
    results = await cache_source.search_by_text("neural networks and attention")
    assert len(results) > 0
    assert results[0].doi == "10.000/ai"

    results_med = await cache_source.search_by_text("heart disease prevention")
    assert len(results_med) > 0
    assert results_med[0].doi == "10.000/med"