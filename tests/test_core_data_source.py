import pytest
from datetime import datetime, timezone, timedelta
from beaver import BeaverDB
from papers.backend.data_sources import get_data_source
from papers.backend.models import CoreUserStatus
from papers.backend.config import Settings

# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def sys_settings():
    """
    Loads the system configuration, ensuring CORE is present.
    """
    return Settings.load_from_yaml()

@pytest.fixture
def db_context(tmp_path):
    """
    Provides a volatile BeaverDB instance for isolation during testing.
    """
    db_path = tmp_path / "test_core_integration.db"
    return BeaverDB(str(db_path))

@pytest.fixture
def user_id():
    return "test_researcher_core_01"


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================

@pytest.mark.anyio
async def test_core_auto_registration(db_context, user_id, sys_settings):
    """
    Tests that the CoreSource adapter automatically registers itself 
    in the user's registry upon first instantiation.
    """
    source = get_data_source("core", settings=sys_settings, user_id=user_id, db=db_context)
    
    registry_db = db_context.dict("adapter_registry")
    assert user_id in registry_db
    
    registry = registry_db[user_id]
    assert "core" in registry["active_adapters"]


@pytest.mark.anyio
async def test_core_daily_quota_exhaustion(db_context, user_id, sys_settings):
    """
    Validates that the adapter stops making requests once the system 
    daily quota is reached.
    """
    # 1. Force an exhausted status in the DB
    status_db = db_context.dict("core_user_status")
    limit = sys_settings.data_sources.core.daily_search_limit
    
    exhausted_status = CoreUserStatus(
        user_id=user_id,
        daily_system_search_count=limit
    )
    status_db[user_id] = exhausted_status.model_dump(mode="json")
    
    # 2. Instantiate the source
    source = get_data_source("core", settings=sys_settings, user_id=user_id, db=db_context)
    
    # 3. Search should return empty list without even calling the API
    results = await source.search_by_text("machine learning", limit=5)
    assert results == []


@pytest.mark.anyio
async def test_core_daily_quota_reset(db_context, user_id, sys_settings):
    """
    Verifies that the daily counter resets if the last_reset date is in the past.
    """
    status_db = db_context.dict("core_user_status")
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    
    # 1. Set a "yesterday" status with maxed out count
    old_status = CoreUserStatus(
        user_id=user_id,
        daily_system_search_count=50,
        last_reset=yesterday
    )
    status_db[user_id] = old_status.model_dump(mode="json")
    
    # 2. Instantiate
    source = get_data_source("core", settings=sys_settings, user_id=user_id, db=db_context)
    
    # 3. Trigger a fetch or search; it should reset the counter internally
    # Note: We use search_by_text which calls _get_status()
    await source.search_by_text("test", limit=1)
    
    # 4. Check DB to see if count was reset
    current_status = CoreUserStatus.model_validate(status_db[user_id])
    assert current_status.daily_system_search_count <= 1 # 0 if API fails, 1 if succeeds
    assert current_status.last_reset.date() == datetime.now(timezone.utc).date()


@pytest.mark.anyio
async def test_core_fallback_logic_disabled(db_context, user_id, sys_settings):
    """
    Tests that if allow_system_fallback is False and the user has no personal key, 
    the search returns empty immediately.
    """
    source = get_data_source("core", settings=sys_settings, user_id=user_id, db=db_context)
    source.config.allow_system_fallback = False
    
    # Ensure no personal key is set in user_adapter_configs
    configs_db = db_context.dict("user_adapter_configs")
    configs_db[user_id] = {"core": {"personal_api_key": None, "use_personal_key": True}}
    
    results = await source.search_by_text("quantum gravity", limit=1)
    assert results == []


@pytest.mark.anyio
async def test_core_personal_key_health_check_failure(db_context, user_id, sys_settings):
    """
    Validates that if a personal key fails (e.g., 401/429), it is marked as
    inactive in the status DB and successfully falls back to the system pool.
    """
    status_db = db_context.dict("core_user_status")
    configs_db = db_context.dict("user_adapter_configs")
    
    # 1. Setup invalid personal key
    configs_db[user_id] = {
        "core": {
            "personal_api_key": "invalid_key_xyz",
            "use_personal_key": True
        }
    }
    
    source = get_data_source("core", settings=sys_settings, user_id=user_id, db=db_context)
    
    import httpx
    from unittest.mock import patch
    
    # Mock 1: The personal key fails (401)
    mock_401 = httpx.Response(401, request=httpx.Request("GET", "https://api.core.ac.uk"))
    # Mock 2: The system fallback succeeds (200)
    mock_200 = httpx.Response(200, json={"results": []}, request=httpx.Request("GET", "https://api.core.ac.uk"))
    
    # Use side_effect to return 401 first, then 200
    with patch.object(httpx.AsyncClient, "request", side_effect=[mock_401, mock_200]):
        await source.search_by_text("test query", limit=1)
        
    # 2. Verify the personal key was marked invalid in the DB
    status = status_db.get(user_id)
    assert status is not None
    assert status["is_key_invalid"] is True