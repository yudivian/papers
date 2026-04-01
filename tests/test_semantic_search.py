import pytest
from unittest.mock import patch, MagicMock
from beaver import BeaverDB
from papers.backend.config import Settings

from papers.backend.models import GlobalDocumentMeta
from papers.backend.data_sources import get_data_source

@pytest.fixture
def semantic_db(tmp_path):
    """
    Creates a temporary BeaverDB instance populated with mock 
    metadata and predictable semantic vectors.
    """
    db_path = tmp_path / "semantic_test.db"
    db = BeaverDB(str(db_path))
    
    docs_db = db.dict("global_documents")
    vectors_db = db.dict("semantic_vectors")
    
    docs_db["10.1000/ml"] = GlobalDocumentMeta(
        doi="10.1000/ml",
        title="Introduction to Machine Learning",
        year=2023,
        file_size=1024,
        storage_uri="local://ml.pdf",
        abstract="A paper about AI and algorithms.",
        keywords=["AI", "Machine Learning"]
    ).model_dump(mode="json")
    
    docs_db["10.1000/bio"] = GlobalDocumentMeta(
        doi="10.1000/bio",
        title="Marine Biology in the Pacific",
        year=2022,
        file_size=2048,
        storage_uri="local://bio.pdf",
        abstract="A paper about fish and oceans.",
        keywords=["Biology", "Oceans"]
    ).model_dump(mode="json")
    
    docs_db["10.1000/dl"] = GlobalDocumentMeta(
        doi="10.1000/dl",
        title="Deep Learning Architecture",
        year=2024,
        file_size=512,
        storage_uri="local://dl.pdf",
        abstract="Advanced neural networks.",
        keywords=["AI", "Deep Learning", "Neural Networks"]
    ).model_dump(mode="json")

    vectors_db["10.1000/ml"] = {"vector": [1.0, 0.0, 0.0]}
    vectors_db["10.1000/dl"] = {"vector": [0.9, 0.1, 0.0]}
    vectors_db["10.1000/bio"] = {"vector": [0.0, 0.0, 1.0]}
    
    return str(db_path)

@pytest.mark.anyio
@patch("papers.backend.data_sources.SemanticEngine")
async def test_semantic_ranking_and_retrieval(MockEngine, semantic_db):
    """
    Validates that BeaverCacheSource correctly applies cosine similarity 
    to rank documents based on the generated semantic vectors.
    """
    mock_engine_instance = MagicMock()
    mock_engine_instance.generate_embedding.return_value = [1.0, 0.0, 0.0]
    MockEngine.return_value = mock_engine_instance

    sys_settings = Settings.load_from_yaml()
    db_instance = BeaverDB(semantic_db)
    cache_source = get_data_source("cache", settings=sys_settings, db=db_instance)

    results = await cache_source.search_by_text("artificial neural networks", limit=3)

    assert len(results) == 3
    assert all(r.source == "cache" for r in results)
    assert results[0].doi == "10.1000/ml"
    assert results[1].doi == "10.1000/dl"
    assert results[2].doi == "10.1000/bio"

@pytest.mark.anyio
async def test_cache_search_empty_database(tmp_path):
    """
    Validates that the adapter handles an empty database gracefully 
    without throwing mathematical errors (e.g., division by zero).
    """
    db_path = tmp_path / "empty.db"
    sys_settings = Settings.load_from_yaml()
    db_instance = BeaverDB(str(db_path))
    cache_source = get_data_source("cache", settings=sys_settings, db=db_instance)
    
    results = await cache_source.search_by_text("machine learning")
    assert len(results) == 0