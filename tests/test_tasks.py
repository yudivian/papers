import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from beaver import BeaverDB

from papers.backend import deps
from papers.backend.config import Settings
from papers.backend.tasks import ingest_paper, manager
from papers.backend.models import GlobalDocumentMeta, KnowledgeBase, DownloadStatus


@pytest.fixture
def sys_settings(tmp_path):
    """
    Hybrid strategy: Loads real configuration but isolates database and storage paths.
    """
    settings = Settings.load_from_yaml()
    settings.database.file = str(tmp_path / "test_tasks.db")
    settings.storage.selected = "local"
    settings.storage.local.base_path = str(tmp_path / "storage_tasks")
    
    deps._global_db = None
    with patch("papers.backend.config.Settings.load_from_yaml", return_value=settings):
        yield settings
    deps._global_db = None

@pytest.fixture
def db_context(sys_settings):
    """
    Provides a fresh, isolated BeaverDB instance for each task test.
    """
    return BeaverDB(sys_settings.database.file)


def test_ingest_paper_full_orchestration(db_context, sys_settings):
    """
    Validates the end-to-end execution of the ingestion pipeline using a patched infrastructure.
    """
    test_db = db_context
    user_id = "user_alpha"
    kb_id = "kb_alpha"
    ticket_id = "ticket_alpha"
    test_doi = "10.1234/test.task"

    kbs_db = test_db.dict("knowledge_bases")
    kbs_db[kb_id] = KnowledgeBase(kb_id=kb_id, owner_id=user_id, name="Test").model_dump(mode="json")

    downloads_db = test_db.dict("downloads")
    downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}

    sys_settings.data_sources.priority = ["openalex"]

    os.makedirs(sys_settings.storage.local.base_path, exist_ok=True)

    mock_meta = GlobalDocumentMeta(
        doi=test_doi,
        title="Task Test",
        year=2024,
        file_size=100,
        storage_uri=f"local://{test_doi.replace('/', '_')}.pdf"
    )

    with patch("papers.backend.tasks.get_task_infrastructure", return_value=(sys_settings, test_db)), \
         patch("papers.backend.tasks.get_data_source") as mock_get_source, \
         patch("papers.backend.tasks._download_asset", new_callable=AsyncMock) as mock_dl, \
         patch("papers.backend.tasks.SemanticEngine") as MockEngine:

        source_instance = MagicMock()
        source_instance.fetch_by_doi = AsyncMock(return_value=mock_meta)
        mock_get_source.return_value = source_instance

        mock_dl.return_value = (b"%PDF-1.4\nFake PDF Content", "application/pdf")

        mock_engine_instance = MagicMock()
        mock_engine_instance.build_semantic_text.return_value = "Fake semantic context string"
        mock_engine_instance.generate_embedding.return_value = [0.1, 0.2, 0.3]
        MockEngine.return_value = mock_engine_instance

        result = ingest_paper.callable(ticket_id, test_doi, user_id, kb_id)

        if not result:
            error_msg = test_db.dict("downloads")[ticket_id].get("error_message", "Unknown internal error")
            pytest.fail(f"Ingestion falló internamente. El error en BD es: {error_msg}")
            
        assert result is True
        
        docs_db = test_db.dict("global_documents")
        assert test_doi in docs_db
        assert docs_db[test_doi]["title"] == "Task Test"
        assert downloads_db[ticket_id]["status"] == DownloadStatus.COMPLETED.value


def test_ingest_paper_cache_bypass(db_context, sys_settings):
    """
    Verifies that the task correctly identifies when a paper is already in the global registry.
    """
    test_db = db_context
    test_doi = "10.already/exists"
    
    docs_db = test_db.dict("global_documents")
    docs_db[test_doi] = {"doi": test_doi, "title": "Existing"}

    with patch("papers.backend.tasks.get_task_infrastructure", return_value=(sys_settings, test_db)):
        result = ingest_paper.callable("ticket_cache", test_doi, "user", "kb")
        assert result is True


def test_ingest_paper_download_resilience(db_context, sys_settings):
    """
    Ensures the task fails gracefully and updates the ticket status if the download fails.
    """
    test_db = db_context
    ticket_id = "ticket_fail"
    test_doi = "10.fail/download"
    
    downloads_db = test_db.dict("downloads")
    downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}

    mock_meta = GlobalDocumentMeta(doi=test_doi, title="Fail", year=2024, file_size=0, storage_uri="")

    with patch("papers.backend.tasks.get_task_infrastructure", return_value=(sys_settings, test_db)), \
         patch("papers.backend.tasks.get_data_source") as mock_get_source, \
         patch("papers.backend.tasks._download_asset", new_callable=AsyncMock) as mock_dl:
             
        source_instance = MagicMock()
        source_instance.fetch_by_doi = AsyncMock(return_value=mock_meta)
        mock_get_source.return_value = source_instance
        
        mock_dl.side_effect = ValueError("Asset acquisition failed")

        result = ingest_paper.callable(ticket_id, test_doi, "user_fail", "kb_fail")

        assert result is False
        assert test_doi not in test_db.dict("global_documents")
        assert downloads_db[ticket_id]["status"] == DownloadStatus.FAILED.value


def test_castor_queue_submission(db_context):
    """
    Verifies that the castor-io Manager correctly enqueues the task in the persistent queue.
    """
    test_db = db_context
    
    with patch.object(manager, "_db", test_db):
        manager._tasks = test_db.dict("castor_tasks")
        manager._pending_tasks = test_db.queue("castor_pending_tasks")
        manager._scheduled_tasks = test_db.queue("castor_scheduled_tasks")
        
        task_handle = ingest_paper.submit(
            ticket_id="ticket_queue",
            doi="10.1234/queue.test",
            user_id="user_q",
            kb_id="kb_q"
        )
    
        assert task_handle.id in manager._tasks
        assert len(manager._pending_tasks) == 1