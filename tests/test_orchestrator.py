import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from beaver import BeaverDB

from papers.backend.orchestrator import DiscoveryOrchestrator
from papers.backend.config import Settings
from papers.backend.models import GlobalDocumentMeta

@pytest.fixture
def mock_context(tmp_path):
    """
    Provisions a minimal settings and DB context for orchestration testing.
    """
    settings = Settings.load_from_yaml()
    settings.data_sources.priority = ["cache", "openalex"]
    
    db_path = tmp_path / "orch.db"
    db = BeaverDB(str(db_path))
    
    return {
        "settings": settings,
        "db": db,
        "user_id": "orch_user"
    }

@pytest.mark.anyio
@patch("papers.backend.orchestrator.get_data_source")
async def test_orchestrator_parallel_search(mock_get_source, mock_context):
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

    orchestrator = DiscoveryOrchestrator(
        settings=mock_context["settings"],
        db=mock_context["db"],
        user_id=mock_context["user_id"]
    )

    results = await orchestrator.search("test query")

    assert isinstance(results, dict)
    assert len(results["cache"]) == 1
    assert results["cache"][0].doi == "doi_1"
    assert len(results["openalex"]) == 1
    assert results["openalex"][0].doi == "doi_2"

@pytest.mark.anyio
@patch("papers.backend.orchestrator.get_data_source")
async def test_orchestrator_waterfall_resolution(mock_get_source, mock_context):
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
        settings=mock_context["settings"],
        db=mock_context["db"],
        user_id=mock_context["user_id"]
    )

    result = await orchestrator.resolve_doi("10.test/1")

    assert result.title == "Found"
    assert cache_source.fetch_by_doi.called
    assert not oa_source.fetch_by_doi.called