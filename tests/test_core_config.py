import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from papers.backend.models import CoreUserStatus
from papers.backend.config import CoreConfig, DataSourcesConfig, OpenAlexConfig

def test_core_config_defaults():
    """
    Validate that CoreConfig initializes with the correct system-level default values.
    """
    config = CoreConfig()
    assert config.base_url == "https://api.core.ac.uk/v3/search/works"
    assert config.daily_search_limit == 20
    assert config.allow_system_fallback is True
    assert config.rate_limit_pause_seconds == 10
    assert config.system_keys == []

def test_core_config_data_binding():
    """
    Validate that CoreConfig correctly binds parameters injected from YAML parsed data.
    """
    data = {
        "system_keys": ["test_key_1", "test_key_2"],
        "daily_search_limit": 50,
        "allow_system_fallback": False,
        "rate_limit_pause_seconds": 5
    }
    config = CoreConfig(**data)
    assert len(config.system_keys) == 2
    assert config.system_keys[0] == "test_key_1"
    assert config.daily_search_limit == 50
    assert config.allow_system_fallback is False
    assert config.rate_limit_pause_seconds == 5

def test_data_sources_config_integration():
    """
    Validate that CoreConfig is properly mounted within the global DataSourcesConfig
    and that the priority list accepts the injected sequence from configuration.
    """
    global_config = DataSourcesConfig(
        priority=["cache", "openalex", "core"],
        openalex=OpenAlexConfig(),
        core=CoreConfig()
    )
    
    assert hasattr(global_config, 'core')
    assert isinstance(global_config.core, CoreConfig)
    assert "core" in global_config.priority

def test_core_user_status_missing_user_id():
    """
    Validate that CoreUserStatus strictly enforces the required user_id field.
    """
    with pytest.raises(ValidationError):
        CoreUserStatus()

def test_core_user_status_defaults():
    """
    Validate that CoreUserStatus initializes with the expected architectural defaults
    when provided with a valid user identifier.
    """
    status = CoreUserStatus(user_id="usr_12345")
    
    assert status.user_id == "usr_12345"
    assert status.personal_key_active is False
    assert status.is_key_invalid is False
    assert status.daily_system_search_count == 0
    assert status.total_system_search_count == 0
    assert isinstance(status.last_reset, datetime)
    assert status.last_reset.tzinfo == timezone.utc

def test_core_user_status_assignment():
    """
    Validate that CoreUserStatus accurately persists all state changes.
    """
    mock_time = datetime.now(timezone.utc)
    status = CoreUserStatus(
        user_id="usr_98765",
        personal_key_active=False,
        daily_system_search_count=19,
        total_system_search_count=1042,
        last_reset=mock_time
    )
    
    assert status.personal_key_active is False
    assert status.daily_system_search_count == 19
    assert status.total_system_search_count == 1042
    assert status.last_reset == mock_time

class MockDatabaseRecord:
    def __init__(self):
        self.user_id = "db_usr_001"
        self.personal_key_active = False
        self.daily_system_search_count = 5
        self.total_system_search_count = 100
        self.last_reset = datetime.now(timezone.utc)

def test_core_user_status_from_attributes():
    """
    Validate that CoreUserStatus can be instantiated from an ORM-like object via from_attributes.
    """
    mock_db_obj = MockDatabaseRecord()
    status = CoreUserStatus.model_validate(mock_db_obj)
    
    assert status.user_id == "db_usr_001"
    assert status.personal_key_active is False
    assert status.daily_system_search_count == 5
    assert status.total_system_search_count == 100