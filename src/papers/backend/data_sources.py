import httpx
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Type
from beaver import BeaverDB

from papers.backend.models import GlobalDocumentMeta

# ==============================================================================
# 1. THE REGISTRY & AUTO-DISCOVERY MECHANISM
# ==============================================================================
_DATA_SOURCES: Dict[str, Type["BaseDataSource"]] = {}

def register_source(cls: Type["BaseDataSource"]) -> Type["BaseDataSource"]:
    """Decorator to automatically register a data source adapter."""
    _DATA_SOURCES[cls.name] = cls
    return cls

def get_data_source(name: str, **kwargs) -> "BaseDataSource":
    """Factory function to instantiate a data source by its configuration name."""
    if name not in _DATA_SOURCES:
        raise ValueError(f"Unknown data source adapter: '{name}'. Available: {list(_DATA_SOURCES.keys())}")
    return _DATA_SOURCES[name](**kwargs)


# ==============================================================================
# 2. THE ABSTRACT BASE CLASS (INTERFACE)
# ==============================================================================
class BaseDataSource(ABC):
    """
    Strict contract for all Data Sources. 
    Whether querying a local database or an external API, they must behave identically.
    """
    name: str

    @abstractmethod
    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        """Fetch exact metadata and PDF download link for a specific DOI."""
        pass

    @abstractmethod
    async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        """Query the source for papers matching a text string."""
        pass


# ==============================================================================
# 3. THE ADAPTERS
# ==============================================================================

@register_source
class BeaverCacheSource(BaseDataSource):
    """
    Adapter 1: The Local Cache.
    Checks if the paper metadata already exists in the system's dictionary.
    """
    name = "cache"

    def __init__(self, db_path: str = "papers.db"):
        self.db = BeaverDB(db_path)
        self.docs_db = self.db.dict("global_documents")

    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        # $O(1)$ dictionary lookup. Zero latency.
        if doi in self.docs_db:
            return GlobalDocumentMeta.model_validate(self.docs_db[doi])
        return None

    async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        # Text search in cache is handled by the Semantic Vector Engine (FastEmbed),
        # not by the metadata dictionary lookup. So this returns empty for the general pipeline.
        return []


@register_source
class OpenAlexSource(BaseDataSource):
    """
    Adapter 2: External OpenAlex API.
    Fetches comprehensive metadata and Open Access PDF links from the web.
    """
    name = "openalex"
    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, mailto: Optional[str] = None, **kwargs):
        # OpenAlex gives higher API limits if you provide an email in the request "mailto"
        self.mailto = mailto

    def _extract_oa_url(self, data: dict) -> str:
        """
        Parses the open_access object to extract a reliable download URI.
        """
        oa_data = data.get("open_access", {})
        
        # 1. Fast fail for closed paywalls
        if not oa_data.get("is_oa"):
            return ""
            
        best_oa = data.get("best_oa_location") or {}
        
        # 2. Prefer direct PDF URLs
        if best_oa.get("pdf_url"):
            return best_oa["pdf_url"]
            
        # 3. Fallback to the landing page (HTML) for the worker to scrape
        if best_oa.get("landing_page_url"):
            return best_oa["landing_page_url"]
            
        return ""

    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        url = f"{self.BASE_URL}/doi:{doi}"
        params = {"mailto": self.mailto} if self.mailto else {}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            title = data.get("title")
            
            if not title:
                return None

            authors = [a["author"]["display_name"] for a in data.get("authorships", [])]
            storage_uri = self._extract_oa_url(data)

            return GlobalDocumentMeta(
                doi=doi,
                title=title,
                authors=authors,
                year=data.get("publication_year") or 0,
                file_size=0,
                storage_uri=storage_uri,
                source=self.name
            )

    async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        url = self.BASE_URL
        params = {"search": query, "per-page": limit}
        if self.mailto: 
            params["mailto"] = self.mailto

        results = []
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            
            if response.status_code != 200:
                return results
            
            for data in response.json().get("results", []):
                doi_url = data.get("doi")
                if not doi_url: 
                    continue
                
                doi = doi_url.replace("https://doi.org/", "")
                storage_uri = self._extract_oa_url(data)

                results.append(GlobalDocumentMeta(
                    doi=doi,
                    title=data.get("title") or "Unknown Title",
                    authors=[a["author"]["display_name"] for a in data.get("authorships", [])],
                    year=data.get("publication_year") or 0,
                    file_size=0,
                    storage_uri=storage_uri,
                    source=self.name
                ))
                
        return results