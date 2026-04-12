import pytest
from datetime import datetime, timezone

from papers.backend.orcid import Orcid
from papers.backend.config import Settings, OrcidConfig
from papers.backend.models import OrcidStatus

@pytest.mark.anyio
async def test_live_orcid_integration():
    """
    Live integration test to verify the actual ORCID API contract.
    This test performs a real HTTP request to orcid.org and validates 
    the parsing logic against live data.
    """
    # 1. Setup actual configuration bypassing other mandatory Settings fields
    config = Settings.model_construct(
        orcid=OrcidConfig(enabled=True, base_url="https://orcid.org")
    )
    client = Orcid(config)
    
    # Target a known, real ORCID ID for validation
    target_orcid = "0000-0002-2345-1387"
    
    # 2. Fetch data from the live API
    payload = await client.fetch_profile(target_orcid)
    
    # Verify the network request succeeded and returned structural data
    assert payload is not None, "Failed to fetch data from the live ORCID API."
    assert "person" in payload, "Live payload is missing the 'person' node."
    assert "activities-summary" in payload, "Live payload is missing the 'activities-summary' node."
    
    # 3. Test parsing logic using the live data payload
    status = OrcidStatus(
        user_id="test_user", 
        orcid_id=target_orcid,
        local_last_checked=datetime.now(timezone.utc)
    )
    
    profile = client.parse_profile(payload, status)
    
    # 4. Assertions on the parsed Pydantic model
    assert profile is not None
    assert profile.orcid_id == target_orcid
    assert "Yudivián" in profile.full_name, "Parsed name does not match the expected live data."
    
    # Validate that arrays are properly initialized and populated
    assert isinstance(profile.works, list), "Works should be parsed as a list."
    assert len(profile.works) > 0, "Expected to find published works in this real profile."
    
    # Validate that external IDs from works are parsed correctly
    has_doi = any(
        ext.type == "doi" 
        for work in profile.works 
        for ext in work.external_ids
    )
    assert has_doi, "Expected to find at least one DOI in the live profile works."

@pytest.mark.anyio
async def test_live_orcid_not_found():
    """
    Ensures the client handles 404 responses gracefully without raising exceptions.
    """
    config = Settings.model_construct(
        orcid=OrcidConfig(enabled=True, base_url="https://orcid.org")
    )
    client = Orcid(config)
    
    # Use a dummy ID formatted correctly but non-existent
    payload = await client.fetch_profile("0000-0000-0000-0000")
    
    assert payload is None, "Expected payload to be None for a non-existent ORCID."