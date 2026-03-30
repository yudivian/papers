import pytest
import os
from datetime import datetime, timezone, timedelta
from beaver import BeaverDB
from papers.backend.data_sources import get_data_source
from papers.backend.models import OpenAlexUserStatus

# ==============================================================================
# FIXTURES
# ==============================================================================

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
async def test_openalex_auto_registration(db_context, user_id):
    """
    Tests that the adapter automatically registers itself in the user's
    registry upon first instantiation.
    """
    source = get_data_source("openalex", user_id=user_id, db=db_context)
    
    registry_db = db_context.dict("adapter_registry")
    assert user_id in registry_db
    
    registry = registry_db[user_id]
    assert "openalex" in registry["active_adapters"]

@pytest.mark.anyio
async def test_live_openalex_fetch_by_doi(db_context, user_id):
    """
    REAL NETWORK TEST: Fetches 'Attention Is All You Need' by DOI.
    Verifies that fetch_by_doi remains functional and unlimited.
    """
    source = get_data_source("openalex", user_id=user_id, db=db_context)
    result = await source.fetch_by_doi("10.48550/arxiv.1706.03762")

    assert result is not None
    assert "Attention" in result.title
    assert result.storage_uri.startswith("http")

@pytest.mark.anyio
async def test_system_quota_enforcement(db_context, user_id):
    """
    Tests that the system blocks searches after reaching the daily_search_limit.
    In config.yaml, the limit is set to 2.
    """
    source = get_data_source("openalex", user_id=user_id, db=db_context)
    
    # 1. First search (allowed)
    res1 = await source.search_by_text("neural networks", limit=1)
    assert len(res1) > 0
    
    # 2. Second search (allowed)
    res2 = await source.search_by_text("deep learning", limit=1)
    assert len(res2) > 0
    
    # 3. Third search (MUST be blocked/return empty because limit is 2)
    res3 = await source.search_by_text("transformers", limit=1)
    assert len(res3) == 0
    
    # 4. Verify fetch_by_doi still works (unlimited)
    res_doi = await source.fetch_by_doi("10.48550/arxiv.1706.03762")
    assert res_doi is not None

@pytest.mark.anyio
async def test_lazy_reset_logic(db_context, user_id):
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
    source = get_data_source("openalex", user_id=user_id, db=db_context)
    
    # 3. Trigger a search; it should reset the counter and succeed
    results = await source.search_by_text("quantum physics", limit=1)
    assert len(results) > 0
    
    # 4. Check DB to see if count was reset to 1 (current search)
    new_status = OpenAlexUserStatus.model_validate(status_db[user_id])
    assert new_status.daily_system_search_count == 1
    assert new_status.last_reset.date() == datetime.now(timezone.utc).date()
    
@pytest.mark.anyio
async def test_fallback_logic_disabled(db_context, user_id):
    """
    Tests that if allow_system_fallback is False, a user with an exhausted 
    personal key is blocked even if the system pool has credits.
    """
    # 1. Setup: User has a personal key but it's marked as exhausted (inactive)
    status_db = db_context.dict("openalex_user_status")
    exhausted_status = OpenAlexUserStatus(
        user_id=user_id,
        personal_api_key="my_broken_key",
        personal_key_active=False  # Key is "dead" for the day
    )
    status_db[user_id] = exhausted_status.model_dump(mode="json")
    
    # 2. Setup: Modify config at runtime to disable fallback
    source = get_data_source("openalex", user_id=user_id, db=db_context)
    source.config.allow_system_fallback = False
    
    # 3. Action: Attempt search
    results = await source.search_by_text("machine learning", limit=1)
    
    # 4. Verification: Should be empty because fallback is disabled 
    # and the personal key is inactive.
    assert len(results) == 0
    
    # 5. Flip the switch: Enable fallback
    source.config.allow_system_fallback = True
    results_with_fallback = await source.search_by_text("machine learning", limit=1)
    
    # 6. Verification: Now it should succeed using the system pool
    assert len(results_with_fallback) > 0