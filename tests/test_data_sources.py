import pytest
import os
from datetime import datetime, timezone, timedelta
from beaver import BeaverDB
from papers.backend.data_sources import get_data_source
from papers.backend.models import OpenAlexUserStatus
from papers.backend.config import Settings

# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def sys_settings():
    return Settings.load_from_yaml()

@pytest.fixture
def db_context(tmp_path):
    """
    Provides a volatile BeaverDB instance for isolation.
    """
    db_path = tmp_path / "test_integration.db"
    return BeaverDB(str(db_path))

@pytest.fixture
def user_id():
    return "test_researcher_01"


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================

@pytest.mark.anyio
async def test_openalex_auto_registration(db_context, user_id, sys_settings):
    """
    Tests that the adapter automatically registers itself in the user's
    registry upon first instantiation.
    """
    source = get_data_source("openalex", settings=sys_settings, user_id=user_id, db=db_context)
    
    registry_db = db_context.dict("adapter_registry")
    assert user_id in registry_db
    
    registry = registry_db[user_id]
    assert "openalex" in registry["active_adapters"]

@pytest.mark.anyio
async def test_live_openalex_fetch_by_doi(db_context, user_id, sys_settings):
    """
    REAL NETWORK TEST: Fetches 'Attention Is All You Need' by DOI.
    Verifies that fetch_by_doi remains functional and unlimited.
    """
    source = get_data_source("openalex", settings=sys_settings, user_id=user_id, db=db_context)
    result = await source.fetch_by_doi("10.48550/arxiv.1706.03762")

    assert result is not None
    assert "Attention" in result.title
    assert result.storage_uri.startswith("http")

@pytest.mark.anyio
async def test_system_quota_enforcement(db_context, user_id, sys_settings):
    """
    Tests that the system blocks searches after reaching the daily_search_limit.
    In config.yaml, the limit is set to 2.
    """
    # [LA SOLUCIÓN] Forzamos el límite a 2 dinámicamente solo para este test
    sys_settings.data_sources.openalex.daily_search_limit = 2
        
    source = get_data_source("openalex", settings=sys_settings, user_id=user_id, db=db_context)
     
    # 1. First search (allowed)
    res1 = await source.search_by_text("neural networks", limit=1)
    assert len(res1) > 0
     
    # 2. Second search (allowed)
    res2 = await source.search_by_text("deep learning", limit=1)
    assert len(res2) > 0
     
    # 3. Third search (MUST be blocked/return empty because limit is 2)
    res3 = await source.search_by_text("transformers", limit=1)
    assert len(res3) == 0

@pytest.mark.anyio
async def test_lazy_reset_logic(db_context, user_id, sys_settings):
    """
    Tests that the adapter resets counters when a new day starts.
    """
    # 1. Mock a state from "yesterday" with exhausted quota
    status_db = db_context.dict("openalex_user_status")
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    
    exhausted_status = OpenAlexUserStatus(
        user_id=user_id,
        daily_system_search_count=100,
        last_reset=yesterday
    )
    status_db[user_id] = exhausted_status.model_dump(mode="json")
    
    # 2. Re-instantiate adapter
    source = get_data_source("openalex", settings=sys_settings, user_id=user_id, db=db_context)
    
    # 3. Trigger a search; it should reset the counter and succeed
    results = await source.search_by_text("quantum physics", limit=1)
    assert len(results) > 0
    
    # 4. Check DB to see if count was reset to 1 (current search)
    new_status = OpenAlexUserStatus.model_validate(status_db[user_id])
    assert new_status.daily_system_search_count == 1
    assert new_status.last_reset.date() == datetime.now(timezone.utc).date()
    
@pytest.mark.anyio
async def test_fallback_logic_disabled(db_context, user_id, sys_settings):
    """
    Tests that if allow_system_fallback is False, a user with an exhausted 
    personal key is blocked even if the system pool has credits.
    """
    status_db = db_context.dict("openalex_user_status")
    exhausted_status = OpenAlexUserStatus(
        user_id=user_id,
        personal_key_active=False
    )
    status_db[user_id] = exhausted_status.model_dump(mode="json")
    
    configs_db = db_context.dict("user_adapter_configs")
    configs_db[user_id] = {"openalex": {"personal_api_key": "my_broken_key"}}
    
    source = get_data_source("openalex", settings=sys_settings, user_id=user_id, db=db_context)
    source.config.allow_system_fallback = False
    
    results = await source.search_by_text("machine learning", limit=1)
    
    assert len(results) == 0
    
    source.config.allow_system_fallback = True
    results_with_fallback = await source.search_by_text("machine learning", limit=1)
    
    assert len(results_with_fallback) > 0