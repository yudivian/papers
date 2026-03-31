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
    Local cache adapter using BeaverDB for O(1) metadata lookups.
    """
    name = "cache"

    def __init__(self, settings: Settings, db: BeaverDB, **kwargs):
        self.db = db
        self.docs_db = self.db.dict("global_documents")

    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        """
        Retrieves a document from the local cache and forces the source flag.
        """
        if doi in self.docs_db:
            meta = GlobalDocumentMeta.model_validate(self.docs_db[doi])
            meta.source = self.name  
            return meta
        return None

    async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        """
        Executes a localized semantic search against cached document metadata.

        This method leverages the SemanticEngine to convert the incoming text query 
        into a mathematical vector representation. It then iterates through all 
        persisted document vectors in the local database, calculating the cosine 
        similarity between the query and each document's conceptual footprint.

        Documents are ranked by their similarity score, and the metadata for the 
        highest-scoring matches is retrieved and returned. The source attribute 
        is explicitly overridden to indicate the local origin of the result.

        Args:
            query: The natural language search string provided by the user.
            limit: The maximum number of relevant documents to return.

        Returns:
            List[GlobalDocumentMeta]: A ranked list of document metadata objects 
                                      that are semantically related to the query.
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
    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, settings: Settings, db: BeaverDB, user_id: str, **kwargs):
        """
        Initializes the source with user context and database access for satellite state.
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
        url = f"{self.BASE_URL}/doi:{doi}"
        data = await self._request_with_health_check(url, {})
        
        if not data:
            return None

        # Extraer instituciones únicas
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
        data = await self._request_with_health_check(self.BASE_URL, params, is_search=True)
        
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