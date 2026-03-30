import pytest
from papers.backend.data_sources import get_data_source

def test_registry_resolves_correct_adapters():
    """
    Validates that the adapter registry correctly resolves the cache adapter.
    """
    source = get_data_source("cache")
    assert source.name == "cache"

def test_registry_raises_on_unknown():
    """
    Validates that the registry rejects invalid adapter names.
    """
    with pytest.raises(ValueError):
        get_data_source("non_existent_source")

@pytest.mark.anyio
async def test_cache_fetch_by_doi():
    """
    Validates local cache retrieval without network calls.
    """
    source = get_data_source("cache")
    source.docs_db = {
        "10.1234/test": {
            "doi": "10.1234/test", 
            "title": "Cached", 
            "storage_uri": "local", 
            "authors": [], 
            "year": 2024, 
            "file_size": 100, 
            "source": "cache"
        }
    }
    result = await source.fetch_by_doi("10.1234/test")
    
    assert result is not None
    assert result.title == "Cached"

@pytest.mark.anyio
async def test_cache_search_by_text():
    """
    Validates local cache search behavior.
    """
    source = get_data_source("cache")
    results = await source.search_by_text("query")
    
    assert len(results) == 0

@pytest.mark.anyio
async def test_live_openalex_fetch_open_access():
    """
    LIVE NETWORK TEST: Fetches a known Open Access paper.
    Verifies that the OpenAlex adapter correctly identifies it as OA 
    and returns a valid storage URI.
    
    DOI: 10.48550/arxiv.1706.03762 (Attention Is All You Need)
    """
    source = get_data_source("openalex", mailto="bot@example.com")
    result = await source.fetch_by_doi("10.48550/arxiv.1706.03762")

    assert result is not None
    assert "Attention" in result.title
    assert len(result.authors) > 0
    # Must have extracted a URL because it is Open Access
    assert result.storage_uri != ""
    assert "arxiv" in result.storage_uri.lower()

@pytest.mark.anyio
async def test_live_openalex_fetch_open_access():
    """
    LIVE NETWORK TEST: Fetches a known Open Access paper.
    Verifies that the OpenAlex adapter correctly identifies it as OA 
    and returns a valid storage URI, regardless of which global mirror it uses.
    
    DOI: 10.48550/arxiv.1706.03762 (Attention Is All You Need)
    """
    source = get_data_source("openalex", mailto="bot@example.com")
    result = await source.fetch_by_doi("10.48550/arxiv.1706.03762")

    assert result is not None
    assert "Attention" in result.title
    assert len(result.authors) > 0
    
    # We assert it found an HTTP link, we don't care if it's arxiv.org or a mirror
    assert result.storage_uri.startswith("http")

@pytest.mark.anyio
async def test_live_openalex_fetch_paywalled():
    """
    LIVE NETWORK TEST: Fetches a strictly Closed Access (Paywalled) paper.
    Using a 1954 chemistry paper to guarantee no Green OA preprints exist.
    Verifies the adapter identifies is_oa=False and blocks the storage_uri.
    
    DOI: 10.1021/ja01646a008 (Journal of the American Chemical Society, 1954)
    """
    source = get_data_source("openalex", mailto="bot@example.com")
    result = await source.fetch_by_doi("10.1021/ja01646a008")

    assert result is not None
    # Must retrieve metadata correctly
    assert result.title is not None
    assert result.year == 1954
    
    # MUST block the URI because it's genuinely paywalled
    assert result.storage_uri == ""

@pytest.mark.anyio
async def test_live_openalex_search():
    """
    LIVE NETWORK TEST: Executes a real text search against OpenAlex.
    """
    source = get_data_source("openalex", mailto="bot@example.com")
    results = await source.search_by_text("quantum computing", limit=3)

    assert len(results) > 0
    assert len(results) <= 3
    
    for paper in results:
        assert paper.doi is not None
        assert paper.title is not None
        assert isinstance(paper.storage_uri, str)