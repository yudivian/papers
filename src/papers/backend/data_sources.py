import httpx
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, List, Dict, Type
from beaver import BeaverDB
from papers.backend.search import SemanticEngine

from papers.backend.models import (
    GlobalDocumentMeta, 
    OpenAlexUserStatus, 
    UserAdapterRegistry
)
from papers.backend.config import Settings

_DATA_SOURCES: Dict[str, Type["BaseDataSource"]] = {}

def register_source(cls: Type["BaseDataSource"]) -> Type["BaseDataSource"]:
    """
    Registry decorator for automatic data source discovery.
    """
    _DATA_SOURCES[cls.name] = cls
    return cls

def get_data_source(name: str, settings: Settings, db: BeaverDB, **kwargs) -> "BaseDataSource":
    """
    Factory to instantiate data sources with the required context.
    """
    if name not in _DATA_SOURCES:
        raise ValueError(f"Unknown adapter: '{name}'")
    return _DATA_SOURCES[name](settings=settings, db=db, **kwargs)

class BaseDataSource(ABC):
    """
    Abstract interface defining the contract for all metadata providers.
    """
    name: str

    @abstractmethod
    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        pass

    @abstractmethod
    async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        pass

@register_source
class BeaverCacheSource(BaseDataSource):
    """
    Local cache adapter using BeaverDB for semantic metadata lookups.
    """
    name = "cache"

    def __init__(self, settings: Settings, db: BeaverDB, **kwargs):
        self.db = db
        self.docs_db = self.db.dict("global_documents")

    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        """
        Retrieves a document from the local cache.
        """
        if doi in self.docs_db:
            meta = GlobalDocumentMeta.model_validate(self.docs_db[doi])
            meta.source = self.name  
            return meta
        return None

    async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        """
        Executes a localized semantic search against cached document metadata.
        """
        vectors_db = self.db.dict("semantic_vectors")
        if not vectors_db:
            return []

        engine = SemanticEngine()
        query_vector = engine.generate_embedding(query)

        def calc_similarity(v1: List[float], v2: List[float]) -> float:
            dot_product = sum(a * b for a, b in zip(v1, v2))
            mag1 = sum(a * a for a in v1) ** 0.5
            mag2 = sum(b * b for b in v2) ** 0.5
            return dot_product / (mag1 * mag2) if mag1 and mag2 else 0.0

        scored_results = []
        for doi, data in vectors_db.items():
            doc_vector = data.get("vector")
            if not doc_vector:
                continue
            
            score = calc_similarity(query_vector, doc_vector)
            scored_results.append((score, doi))

        scored_results.sort(key=lambda x: x[0], reverse=True)
        top_dois = [doi for score, doi in scored_results[:limit]]

        results = []
        for doi in top_dois:
            if doi in self.docs_db:
                meta = GlobalDocumentMeta.model_validate(self.docs_db[doi])
                meta.source = self.name
                results.append(meta)

        return results

@register_source
class OpenAlexSource(BaseDataSource):
    """
    Autonomous OpenAlex adapter with built-in quota management and health monitoring.
    """
    name = "openalex"

    def __init__(self, settings: Settings, db: BeaverDB, user_id: str, **kwargs):
        """
        Initializes the source with user context and database access.
        """
        self.user_id = user_id
        self.db = db
        self.logger = logging.getLogger(__name__)
        self.config = settings.data_sources.openalex
        self.registry_db = self.db.dict("adapter_registry")
        self.status_db = self.db.dict("openalex_user_status")
        
        self._ensure_registration()

    def _ensure_registration(self) -> None:
        """
        Implements the Auto-Registration logic to track active user adapters.
        """
        registry_data = self.registry_db.get(self.user_id)
        if not registry_data:
            registry = UserAdapterRegistry(user_id=self.user_id, active_adapters=[self.name])
        else:
            registry = UserAdapterRegistry.model_validate(registry_data)
            if self.name not in registry.active_adapters:
                registry.active_adapters.append(self.name)
        
        registry.last_interaction[self.name] = datetime.now(timezone.utc)
        self.registry_db[self.user_id] = registry.model_dump(mode="json")

    def _get_status(self) -> OpenAlexUserStatus:
        """
        Retrieves or initializes the satellite state for the current user.
        """
        data = self.status_db.get(self.user_id)
        if not data:
            status = OpenAlexUserStatus(user_id=self.user_id)
        else:
            status = OpenAlexUserStatus.model_validate(data)
        
        now = datetime.now(timezone.utc)
        if status.last_reset.date() < now.date():
            status.daily_system_search_count = 0
            status.personal_key_active = True
            status.last_reset = now
            self.status_db[self.user_id] = status.model_dump(mode="json")
            
        return status

    async def _request_with_health_check(self, url: str, params: dict, is_search: bool = False) -> Optional[dict]:
        """
        Core execution engine that monitors API health and credit consumption.
        """
        status = self._get_status()
        keys_to_try = []
        
        if status.personal_api_key and status.personal_key_active:
            keys_to_try.append(("personal", status.personal_api_key))
        
        if not is_search:
            for k in self.config.system_keys:
                keys_to_try.append(("system", k))
        else:
            if not status.personal_api_key or self.config.allow_system_fallback:
                for k in self.config.system_keys:
                    keys_to_try.append(("system", k))

        for key_type, key_value in keys_to_try:
            if is_search and key_type == "system":
                if status.daily_system_search_count >= self.config.daily_search_limit:
                    continue

            current_params = params.copy()
            current_params["api_key"] = key_value

            async with httpx.AsyncClient(timeout=20.0) as client:
                try:
                    response = await client.get(url, params=current_params)
                    
                    remaining = int(response.headers.get("X-RateLimit-Remaining", 100000))
                    if key_type == "personal" and (remaining <= 0 or response.status_code in (401, 403, 429)):
                        status.personal_key_active = False
                        self.status_db[self.user_id] = status.model_dump(mode="json")
                        continue

                    if response.status_code == 200:
                        if is_search and key_type == "system":
                            status.daily_system_search_count += 1
                            self.status_db[self.user_id] = status.model_dump(mode="json")
                        return response.json()
                    
                    elif response.status_code == 404:
                        return None
                        
                except Exception as e:
                    self.logger.error(f"OpenAlex request failed for key {key_type}: {e}")
                    continue
        
        return None
    
    def _extract_oa_url(self, data: dict) -> str:
        """
        Extracts the best available Open Access URL.
        """
        oa_data = data.get("open_access", {})
        if not oa_data.get("is_oa"):
            return ""
        best_oa = data.get("best_oa_location") or {}
        return best_oa.get("pdf_url") or best_oa.get("landing_page_url") or ""
    
    def _reconstruct_abstract(self, inverted_index: Optional[dict]) -> str:
        """
        Reconstructs the full abstract text from OpenAlex's inverted index format.
        """
        if not inverted_index:
            return ""
        try:
            max_index = max([pos for positions in inverted_index.values() for pos in positions])
            words = [""] * (max_index + 1)
            for word, positions in inverted_index.items():
                for pos in positions:
                    words[pos] = word
            return " ".join(words).strip()
        except Exception as e:
            self.logger.warning(f"Failed to reconstruct abstract: {e}")
            return ""

    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        """
        Unlimited DOI lookup operation. Does not consume search quotas.
        """
        url = f"{self.config.base_url}/doi:{doi}"
        data = await self._request_with_health_check(url, {})
        
        if not data:
            return None

        institutions = list({
            inst["display_name"] 
            for a in data.get("authorships", []) 
            for inst in a.get("institutions", [])
            if inst.get("display_name")
        })

        return GlobalDocumentMeta(
            doi=doi,
            title=data.get("title") or "Unknown",
            authors=[a["author"]["display_name"] for a in data.get("authorships", [])],
            year=data.get("publication_year") or 0,
            file_size=0,
            storage_uri=self._extract_oa_url(data),
            mime_type="application/pdf",
            file_extension=".pdf",
            source=self.name,
            abstract=self._reconstruct_abstract(data.get("abstract_inverted_index")),
            keywords=[c["display_name"] for c in data.get("concepts", [])[:10]],
            institutions=institutions
        )

    async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        """
        Restricted text search operation. Subject to daily user quotas.
        """
        params = {"search": query, "per-page": limit}        
        data = await self._request_with_health_check(self.config.base_url, params, is_search=True)
        
        if not data:
            return []

        results = []
        for item in data.get("results", []):
            doi_url = item.get("doi")
            if not doi_url:
                continue
            
            institutions = list({
                inst["display_name"] 
                for a in item.get("authorships", []) 
                for inst in a.get("institutions", [])
                if inst.get("display_name")
            })

            results.append(GlobalDocumentMeta(
                doi=doi_url.replace("https://doi.org/", ""),
                title=item.get("title") or "Unknown",
                authors=[a["author"]["display_name"] for a in item.get("authorships", [])],
                year=item.get("publication_year") or 0,
                file_size=0,
                storage_uri=self._extract_oa_url(item),
                source=self.name,
                abstract=self._reconstruct_abstract(item.get("abstract_inverted_index")),
                keywords=[c["display_name"] for c in item.get("concepts", [])[:10]],
                institutions=institutions
            ))
        return results