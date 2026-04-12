import httpx
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from papers.backend.models import (
    OrcidProfileResponse,
    OrcidAffiliation,
    OrcidWork,
    OrcidExternalId,
    OrcidStatus
)
from papers.backend.config import Settings

logger = logging.getLogger(__name__)

class Orcid:
    """
    Client for interacting with the public ORCID API via Content Negotiation.
    This avoids the need for OAuth or registered API keys for public data.
    """

    def __init__(self, config: Settings):
        self.config = config.orcid
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "Papers-Local-Knowledge-System/1.0"
        }

    async def fetch_profile(self, orcid_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches the raw JSON profile for a given ORCID ID.
        Returns None if the fetch fails (e.g., network error or invalid ID).
        """
        if not self.config.enabled:
            logger.warning("ORCID integration is disabled in settings.")
            return None

        url = f"{self.config.base_url}/{orcid_id}"
        
        try:
            # FIX: Add follow_redirects=True here
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, headers=self.headers, timeout=10.0)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching ORCID {orcid_id}: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Network error fetching ORCID {orcid_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error fetching ORCID {orcid_id}: {str(e)}")
            
        return None

    def _extract_external_ids(self, external_ids_node: Optional[Dict[str, Any]]) -> List[OrcidExternalId]:
        """Helper to extract a list of external IDs from an ORCID node."""
        if not external_ids_node:
            return []
        
        extracted = []
        ext_list = external_ids_node.get("external-id", [])
        for ext in ext_list:
            url = None
            if ext.get("external-id-url") and isinstance(ext["external-id-url"], dict):
                url = ext["external-id-url"].get("value")
                
            extracted.append(OrcidExternalId(
                type=ext.get("external-id-type", "unknown"),
                value=ext.get("external-id-value", ""),
                url=url
            ))
        return extracted

    def _extract_affiliations(self, affiliation_group: List[Dict[str, Any]], summary_key: str) -> List[OrcidAffiliation]:
        """Helper to extract education, employment, or qualification summaries."""
        extracted = []
        for group in affiliation_group:
            summaries = group.get("summaries", [])
            for summary_wrap in summaries:
                summary = summary_wrap.get(summary_key, {})
                if not summary:
                    continue
                
                org = summary.get("organization", {})
                org_name = org.get("name", "Unknown Organization")
                role = summary.get("role-title", "Unknown Role")
                
                start_year = None
                if summary.get("start-date"):
                    start_year = summary["start-date"].get("year", {}).get("value")
                    
                end_year = None
                if summary.get("end-date"):
                    end_year = summary["end-date"].get("year", {}).get("value")
                    
                extracted.append(OrcidAffiliation(
                    organization=org_name,
                    role=role,
                    start_year=start_year,
                    end_year=end_year
                ))
        return extracted

    def parse_profile(self, payload: Dict[str, Any], status: OrcidStatus) -> OrcidProfileResponse:
        """
        Transforms the raw ORCID JSON payload into the clean Pydantic model for the frontend.
        """
        person = payload.get("person", {})
        activities = payload.get("activities-summary", {})
        
        name_node = person.get("name", {})
        given = name_node.get("given-names", {}).get("value", "") if name_node.get("given-names") else ""
        family = name_node.get("family-name", {}).get("value", "") if name_node.get("family-name") else ""
        full_name = f"{given} {family}".strip()
        
        credit_name = name_node.get("credit-name", {}).get("value") if name_node.get("credit-name") else None
        biography = person.get("biography", {}).get("content") if person.get("biography") else None
        
        keywords = []
        for kw_node in person.get("keywords", {}).get("keyword", []):
            keywords.append(kw_node.get("content", ""))

        urls = []
        for url_node in person.get("researcher-urls", {}).get("researcher-url", []):
            urls.append({
                "name": url_node.get("url-name", ""),
                "url": url_node.get("url", {}).get("value", "") if url_node.get("url") else ""
            })
            
        profile_external_ids = self._extract_external_ids(person.get("external-identifiers", {}))

        employments = self._extract_affiliations(
            activities.get("employments", {}).get("affiliation-group", []), 
            "employment-summary"
        )
        educations = self._extract_affiliations(
            activities.get("educations", {}).get("affiliation-group", []), 
            "education-summary"
        )
        qualifications = self._extract_affiliations(
            activities.get("qualifications", {}).get("affiliation-group", []), 
            "qualification-summary"
        )

        works = []
        for work_group in activities.get("works", {}).get("group", []):
            for work_summary_wrap in work_group.get("work-summary", []):
                
                title = "Untitled"
                if work_summary_wrap.get("title") and work_summary_wrap["title"].get("title"):
                    title = work_summary_wrap["title"]["title"].get("value", "Untitled")
                
                pub_date = work_summary_wrap.get("publication-date")
                pub_year = pub_date.get("year", {}).get("value") if pub_date else None
                
                journal_title = None
                if work_summary_wrap.get("journal-title"):
                    journal_title = work_summary_wrap["journal-title"].get("value")
                    
                url = None
                if work_summary_wrap.get("url"):
                    url = work_summary_wrap["url"].get("value")
                    
                source = None
                if work_summary_wrap.get("source") and work_summary_wrap["source"].get("source-name"):
                    source = work_summary_wrap["source"]["source-name"].get("value")
                
                c_date = work_summary_wrap.get("created-date", {}).get("value")
                m_date = work_summary_wrap.get("last-modified-date", {}).get("value")

                work = OrcidWork(
                    title=title,
                    type=work_summary_wrap.get("type", "unknown"),
                    publication_year=pub_year,
                    external_ids=self._extract_external_ids(work_summary_wrap.get("external-ids")),
                    url=url,
                    journal_title=journal_title,
                    source=source,
                    created_date=c_date,
                    last_modified_date=m_date
                )
                works.append(work)


        sync_status = "up_to_date"

        return OrcidProfileResponse(
            sync_status=sync_status,
            last_updated=status.local_last_checked,
            orcid_id=status.orcid_id,
            full_name=full_name,
            credit_name=credit_name,
            biography=biography,
            keywords=keywords,
            researcher_urls=urls,
            external_ids=profile_external_ids,
            employments=employments,
            educations=educations,
            qualifications=qualifications,
            works=works
        )