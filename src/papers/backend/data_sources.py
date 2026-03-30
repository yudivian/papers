import httpx
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, List, Dict, Type
from beaver import BeaverDB

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

def get_data_source(name: str, **kwargs) -> "BaseDataSource":
    """
    Factory to instantiate data sources with the required context.
    """
    if name not in _DATA_SOURCES:
        raise ValueError(f"Unknown adapter: '{name}'")
    return _DATA_SOURCES[name](**kwargs)

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
    Local cache adapter using BeaverDB for O(1) metadata lookups.
    """
    name = "cache"

    def __init__(self, db_path: str = "papers.db", **kwargs):
        self.db = BeaverDB(db_path)
        self.docs_db = self.db.dict("global_documents")

    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        if doi in self.docs_db:
            return GlobalDocumentMeta.model_validate(self.docs_db[doi])
        return None

    async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        return []

@register_source
class OpenAlexSource(BaseDataSource):
    """
    Autonomous OpenAlex adapter with built-in quota management and health monitoring.
    """
    name = "openalex"
    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, user_id: str, db: BeaverDB, **kwargs):
        """
        Initializes the source with user context and database access for satellite state.
        """
        self.user_id = user_id
        self.db = db
        self.logger = logging.getLogger(__name__)
        
        settings = Settings.load_from_yaml()
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
        Includes the Lazy Reset logic for daily quota cycles.
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
        Implements key rotation, BYOK priority, and institutional fallback logic.
        """
        status = self._get_status()
        keys_to_try = []
        
        # 1. PRIORIDAD: Llave Personal (BYOK) si existe y está sana
        if status.personal_api_key and status.personal_key_active:
            keys_to_try.append(("personal", status.personal_api_key))
        
        # 2. POOL INSTITUCIONAL Y FALLBACK:
        if not is_search:
            # Para DOI: Siempre se añade el pool porque es ilimitado y gratis.
            for k in self.config.system_keys:
                keys_to_try.append(("system", k))
        else:
            # Para Búsqueda: Solo se añade si no hay llave personal O si el fallback está permitido.
            if not status.personal_api_key or self.config.allow_system_fallback:
                for k in self.config.system_keys:
                    keys_to_try.append(("system", k))

        # 3. BUCLE DE EJECUCIÓN
        for key_type, key_value in keys_to_try:
            # Bloqueo estricto por cuota del sistema
            if is_search and key_type == "system":
                if status.daily_system_search_count >= self.config.daily_search_limit:
                    continue

            current_params = params.copy()
            current_params["api_key"] = key_value

            async with httpx.AsyncClient(timeout=20.0) as client:
                try:
                    response = await client.get(url, params=current_params)
                    
                    # A) Monitorización de Salud (Para llaves personales)
                    remaining = int(response.headers.get("X-RateLimit-Remaining", 100000))
                    # Si la llave no tiene créditos (429) o es inválida (401, 403), se "apaga"
                    if key_type == "personal" and (remaining <= 0 or response.status_code in (401, 403, 429)):
                        status.personal_key_active = False
                        self.status_db[self.user_id] = status.model_dump(mode="json")
                        continue

                    # B) Éxito: Consumo de Cuota y Retorno
                    if response.status_code == 200:
                        if is_search and key_type == "system":
                            status.daily_system_search_count += 1
                            self.status_db[self.user_id] = status.model_dump(mode="json")
                        return response.json()
                    
                    # C) Prevención del "Bucle Infinito" en 404
                    elif response.status_code == 404:
                        # Si no existe en OpenAlex, no existirá con otra llave.
                        return None
                        
                except Exception as e:
                    self.logger.error(f"OpenAlex request failed for key {key_type}: {e}")
                    continue
        
        return None
    
    
    def _extract_oa_url(self, data: dict) -> str:
        oa_data = data.get("open_access", {})
        if not oa_data.get("is_oa"):
            return ""
        best_oa = data.get("best_oa_location") or {}
        return best_oa.get("pdf_url") or best_oa.get("landing_page_url") or ""

    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        """
        Unlimited DOI lookup operation. Does not consume search quotas.
        """
        url = f"{self.BASE_URL}/doi:{doi}"
        data = await self._request_with_health_check(url, {})
        
        if not data:
            return None

        return GlobalDocumentMeta(
            doi=doi,
            title=data.get("title", "Unknown"),
            authors=[a["author"]["display_name"] for a in data.get("authorships", [])],
            year=data.get("publication_year") or 0,
            file_size=0,
            storage_uri=self._extract_oa_url(data),
            source=self.name
        )

    async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        """
        Restricted text search operation. Subject to daily user quotas.
        """
        params = {"search": query, "per-page": limit}
        data = await self._request_with_health_check(self.BASE_URL, params, is_search=True)
        
        if not data:
            return []

        results = []
        for item in data.get("results", []):
            doi_url = item.get("doi")
            if not doi_url:
                continue
            
            results.append(GlobalDocumentMeta(
                doi=doi_url.replace("https://doi.org/", ""),
                title=item.get("title") or "Unknown",
                authors=[a["author"]["display_name"] for a in item.get("authorships", [])],
                year=item.get("publication_year") or 0,
                file_size=0,
                storage_uri=self._extract_oa_url(item),
                source=self.name
            ))
        return results