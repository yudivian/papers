import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from beaver import BeaverDB

from papers.backend import deps
from papers.backend.orchestrator import DiscoveryOrchestrator
from papers.backend.config import Settings
from papers.backend.models import GlobalDocumentMeta

@pytest.fixture
def sys_settings(tmp_path):
    """
    Hybrid strategy: Loads real configuration for structure/keys but isolates
    database and storage to a temporary directory for orchestration tests.
    """
    settings = Settings.load_from_yaml()
    settings.database.file = str(tmp_path / "test_orchestrator.db")
    settings.storage.selected = "local"
    settings.storage.local.base_path = str(tmp_path / "storage_orch")
    
    # Reset global singleton to force reload with new settings
    deps._global_db = None
    with patch("papers.backend.config.Settings.load_from_yaml", return_value=settings):
        yield settings
    deps._global_db = None

@pytest.fixture
def db_context(sys_settings):
    """
    Provides a fresh, isolated BeaverDB instance for each orchestrator test.
    """
    return BeaverDB(sys_settings.database.file)

@pytest.fixture
def user_id():
    return "orch_user"

@pytest.mark.anyio
@patch("papers.backend.orchestrator.get_data_source")
async def test_orchestrator_parallel_search(mock_get_source, db_context, sys_settings, user_id):
    """
    Verifies that the orchestrator executes parallel queries and maps results accurately.

    This test mocks multiple data sources returning different results and 
    asserts that the resulting dictionary contains all expected source keys 
    with their respective document payloads.
    """
    doc_cache = GlobalDocumentMeta(doi="doi_1", title="Cache Result", year=2024, file_size=0, storage_uri="")
    doc_oa = GlobalDocumentMeta(doi="doi_2", title="OA Result", year=2024, file_size=0, storage_uri="")

    def side_effect(name, **kwargs):
        source = MagicMock()
        if name == "cache":
            source.search_by_text = AsyncMock(return_value=[doc_cache])
        else:
            source.search_by_text = AsyncMock(return_value=[doc_oa])
        return source

    mock_get_source.side_effect = side_effect

    sys_settings.data_sources.priority = ["cache", "openalex"] # Set explicit for test
    orchestrator = DiscoveryOrchestrator(
        settings=sys_settings,
        db=db_context,
        user_id=user_id
    )

    results = await orchestrator.search("test query")

    assert isinstance(results, dict)
    assert len(results["cache"]) == 1
    assert results["cache"][0].doi == "doi_1"
    assert len(results["openalex"]) == 1
    assert results["openalex"][0].doi == "doi_2"

@pytest.mark.anyio
@patch("papers.backend.orchestrator.get_data_source")
async def test_orchestrator_waterfall_resolution(mock_get_source, db_context, sys_settings, user_id):
    """
    Validates the prioritized waterfall strategy for DOI resolution.

    Ensures that if a document is found in the first source (cache), the 
    orchestrator returns immediately without querying subsequent sources.
    """
    doc = GlobalDocumentMeta(doi="10.test/1", title="Found", year=2024, file_size=0, storage_uri="")
    
    cache_source = MagicMock()
    cache_source.fetch_by_doi = AsyncMock(return_value=doc)
    
    oa_source = MagicMock()
    oa_source.fetch_by_doi = AsyncMock(return_value=None)

    mock_get_source.side_effect = [cache_source, oa_source]

    orchestrator = DiscoveryOrchestrator(
        settings=sys_settings,
        db=db_context,
        user_id=user_id
    )

    result = await orchestrator.resolve_doi("10.test/1")

    assert result.title == "Found"
    assert cache_source.fetch_by_doi.called
    assert not oa_source.fetch_by_doi.called
    



@pytest.mark.anyio
async def test_orchestrator_executes_core_source(db_context, sys_settings, user_id):
    """
    Verifies that the orchestrator calls search_by_text on CoreSource
    if 'core' is in the priority list.
    """
    # Force the priority locally for the test
    sys_settings.data_sources.priority = ["core"]
    
    orchestrator = DiscoveryOrchestrator(settings=sys_settings, db=db_context, user_id=user_id)
    
    # Mock the adapter's specific method to avoid real HTTP requests
    with patch("papers.backend.data_sources.CoreSource.search_by_text") as mock_core_search:
        mock_core_search.return_value = []

        await orchestrator.search("test query", limit=5)

        # The orchestrator should have called the CORE adapter
        mock_core_search.assert_called_once()