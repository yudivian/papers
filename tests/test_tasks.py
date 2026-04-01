import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from beaver import BeaverDB

from papers.backend.tasks import ingest_paper, manager
from papers.backend.models import GlobalDocumentMeta, KnowledgeBase, DownloadStatus

@pytest.fixture
def test_env():
    """
    Provisions a completely isolated filesystem environment for integration testing.
    """
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_tasks.db")
    storage_path = os.path.join(temp_dir, "storage")
    os.makedirs(storage_path)
    
    yield {
        "db_path": db_path,
        "storage_path": storage_path,
        "temp_dir": temp_dir
    }
    
    shutil.rmtree(temp_dir)

def test_ingest_paper_full_orchestration(test_env):
    """
    Validates the end-to-end execution of the ingestion pipeline.
    """
    test_db = BeaverDB(test_env["db_path"])
    user_id = "user_alpha"
    kb_id = f"kb_{user_id}"
    test_doi = "10.1234/success.path"
    ticket_id = "ticket_123"
    
    kbs_db = test_db.dict("knowledge_bases")
    kbs_db[kb_id] = KnowledgeBase(
        kb_id=kb_id, owner_id=user_id, name="Test KB"
    ).model_dump(mode="json")

    downloads_db = test_db.dict("downloads")
    downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}

    mock_meta = GlobalDocumentMeta(
        doi=test_doi,
        title="Valid Test Paper",
        authors=["Author A"],
        year=2026,
        storage_uri="https://example.com/paper.pdf",
        mime_type="application/pdf",
        file_extension=".pdf",
        file_size=0,
        source="openalex"
    )

    with patch("papers.backend.tasks.db", test_db), \
         patch("papers.backend.tasks.settings") as mock_settings, \
         patch("papers.backend.tasks.get_data_source") as mock_get_source, \
         patch("papers.backend.tasks._download_asset", new_callable=AsyncMock) as mock_dl, \
         patch("papers.backend.tasks.SemanticEngine") as mock_engine:

        mock_settings.storage.selected = "local"
        mock_settings.storage.local.base_path = test_env["storage_path"]
        mock_settings.data_sources.priority = ["openalex"]
        mock_settings.database.file = test_env["db_path"]

        source_instance = MagicMock()
        source_instance.fetch_by_doi = AsyncMock(return_value=mock_meta)
        mock_get_source.return_value = source_instance
        mock_dl.return_value = b"%PDF-1.4 Mock Data"
        
        mock_engine.return_value.build_semantic_text.return_value = "Mock Text Context"
        mock_engine.return_value.generate_embedding.return_value = [0.1, 0.2, 0.3]

        result = ingest_paper.callable(ticket_id, test_doi, user_id, kb_id)

        error_msg = downloads_db[ticket_id].get("error_message", "No error recorded")
        assert result is True, f"Worker fail internally: {error_msg}"
        
        docs_db = test_db.dict("global_documents")
        assert test_doi in docs_db
        assert docs_db[test_doi]["file_size"] > 0
        
        assert downloads_db[ticket_id]["status"] == DownloadStatus.COMPLETED.value

def test_ingest_paper_cache_bypass(test_env):
    """
    Ensures the pipeline halts immediately if the document already exists locally.
    """
    test_db = BeaverDB(test_env["db_path"])
    test_doi = "10.1234/cached.paper"
    kb_id = "kb_cache"
    ticket_id = "ticket_cache"
    
    docs_db = test_db.dict("global_documents")
    docs_db[test_doi] = {"doi": test_doi, "title": "Cached", "storage_uri": "local"}

    with patch("papers.backend.tasks.db", test_db), \
         patch("papers.backend.tasks.get_data_source") as mock_get_source:
        
        result = ingest_paper.callable(ticket_id, test_doi, "user_x", kb_id)
        
        assert result is True
        mock_get_source.assert_not_called()

def test_ingest_paper_download_resilience(test_env):
    """
    Validates failure containment when the remote PDF is unavailable.
    """
    test_db = BeaverDB(test_env["db_path"])
    test_doi = "10.1234/broken.link"
    ticket_id = "ticket_fail"
    
    downloads_db = test_db.dict("downloads")
    downloads_db[ticket_id] = {"status": DownloadStatus.PENDING.value}
    
    mock_meta = GlobalDocumentMeta(
        doi=test_doi,
        title="Broken Paper",
        authors=[],
        year=2026,
        storage_uri="https://example.com/404.pdf",
        mime_type="application/pdf",
        file_extension=".pdf",
        file_size=0,
        source="openalex"
    )

    with patch("papers.backend.tasks.db", test_db), \
         patch("papers.backend.tasks.settings") as mock_settings, \
         patch("papers.backend.tasks.get_data_source") as mock_get_source, \
         patch("papers.backend.tasks._download_asset", new_callable=AsyncMock) as mock_dl:
             
        mock_settings.storage.selected = "local"
        mock_settings.storage.local.base_path = test_env["storage_path"]
        mock_settings.data_sources.priority = ["openalex"]
        mock_settings.database.file = test_env["db_path"]

        source_instance = MagicMock()
        source_instance.fetch_by_doi = AsyncMock(return_value=mock_meta)
        mock_get_source.return_value = source_instance
        mock_dl.return_value = None

        result = ingest_paper.callable(ticket_id, test_doi, "user_fail", "kb_fail")

        assert result is False
        assert test_doi not in test_db.dict("global_documents")
        assert downloads_db[ticket_id]["status"] == DownloadStatus.FAILED.value

def test_castor_queue_submission(test_env):
    """
    Verifies that the castor-io Manager correctly enqueues the task.
    """
    test_db = BeaverDB(test_env["db_path"])
    
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
        
        assert task_handle is not None
        assert task_handle.id is not None
        
        queued_tasks = test_db.dict("castor_tasks")
        assert task_handle.id in queued_tasks
        assert queued_tasks[task_handle.id]["status"] == "pending"
        assert queued_tasks[task_handle.id]["task_name"] == "ingest_paper"