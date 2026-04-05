import httpx
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, List, Dict, Type, Any
from beaver import BeaverDB
from papers.backend.search import SemanticEngine
from pydantic import BaseModel, Field

from papers.backend.models import (
    GlobalDocumentMeta,
    OpenAlexUserStatus,
    UserAdapterRegistry,
    OpenAlexUserStatus,
)
from papers.backend.config import Settings
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


_DATA_SOURCES: Dict[str, Type["BaseDataSource"]] = {}


def register_source(cls: Type["BaseDataSource"]) -> Type["BaseDataSource"]:
    """
    Registry decorator for automatic data source discovery.
    """
    _DATA_SOURCES[cls.name] = cls
    return cls


def get_data_source(
    name: str, settings: Settings, db: BeaverDB, **kwargs
) -> "BaseDataSource":
    """
    Factory to instantiate data sources with the required context.
    """
    if name not in _DATA_SOURCES:
        raise ValueError(f"Unknown adapter: '{name}'")
    return _DATA_SOURCES[name](settings=settings, db=db, **kwargs)


class AdapterConfig(BaseModel):
    """
    Base configuration schema for data source adapters.
    """

    pass


class OpenAlexConfig(AdapterConfig):
    """
    Configuration schema defining the required parameters for the OpenAlex data source.
    """

    personal_api_key: Optional[str] = Field(
        default=None,
        title="Personal API Key",
        description="Optional API key to access higher rate limits and priority pools.",
        json_schema_extra={"ui_widget": "password"},
    )

    use_personal_key: bool = Field(
        default=True,
        title="Enable Personal Key",
        description="Turn off to temporarily use the system pool without deleting your saved key.",
    )


class BaseDataSource(ABC):
    """
    Abstract interface defining the contract for all metadata providers.
    """

    name: str
    config_schema: Type[AdapterConfig] = AdapterConfig

    @abstractmethod
    async def fetch_by_doi(self, doi: str) -> Optional[GlobalDocumentMeta]:
        pass

    @abstractmethod
    async def search_by_text(
        self, query: str, limit: int = 10
    ) -> List[GlobalDocumentMeta]:
        pass

    config_schema: Type[AdapterConfig] = AdapterConfig

    @classmethod
    def get_ui_schema(cls) -> Dict[str, Any]:
        """
        Generates a JSON Schema representation of the adapter's configuration requirements.
        """
        return cls.config_schema.model_json_schema()

    @classmethod
    def get_config_state(
        cls, user_id: str, db: Any, settings: Optional[Settings] = None
    ) -> Dict[str, Any]:
        """
        Retrieves adapter-specific internal state to be merged with the user's configuration.
        Defaults to an empty dictionary.
        """
        return {}

    @classmethod
    def apply_config_side_effects(
        cls, user_id: str, config: AdapterConfig, db: Any
    ) -> None:
        """
        Executes adapter-specific state mutations upon configuration updates.
        Defaults to a no-operation.
        """
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

    async def search_by_text(
        self, query: str, limit: int = 10
    ) -> List[GlobalDocumentMeta]:
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
    config_schema = OpenAlexConfig

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
            registry = UserAdapterRegistry(
                user_id=self.user_id, active_adapters=[self.name]
            )
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

        status.total_system_search_count = self.config.daily_search_limit

        now = datetime.now(timezone.utc)
        if status.last_reset.date() < now.date():
            status.daily_system_search_count = 0
            status.personal_key_active = True
            status.last_reset = now
            self.status_db[self.user_id] = status.model_dump(mode="json")

        return status

    # async def _request_with_health_check(self, url: str, params: dict, is_search: bool = False) -> Optional[dict]:
    #     """
    #     Core execution engine that monitors API health and credit consumption.
    #     """
    #     status = self._get_status()

    #     configs_db = self.db.dict("user_adapter_configs")
    #     user_configs = configs_db.get(self.user_id, {})
    #     openalex_config = user_configs.get(self.name, {})
    #     personal_api_key = openalex_config.get("personal_api_key")

    #     keys_to_try = []

    #     if personal_api_key and status.personal_key_active:
    #         keys_to_try.append(("personal", personal_api_key))

    #     if not is_search:
    #         for k in self.config.system_keys:
    #             keys_to_try.append(("system", k))
    #     else:
    #         if not personal_api_key or self.config.allow_system_fallback:
    #             for k in self.config.system_keys:
    #                 keys_to_try.append(("system", k))

    #     for key_type, key_value in keys_to_try:
    #         if is_search and key_type == "system":
    #             if status.daily_system_search_count >= self.config.daily_search_limit:
    #                 continue

    #         current_params = params.copy()
    #         current_params["api_key"] = key_value

    #         async with httpx.AsyncClient(timeout=20.0) as client:
    #             try:
    #                 response = await client.get(url, params=current_params)

    #                 remaining = int(response.headers.get("X-RateLimit-Remaining", 100000))
    #                 if key_type == "personal" and (remaining <= 0 or response.status_code in (401, 403, 429)):
    #                     status.personal_key_active = False
    #                     self.status_db[self.user_id] = status.model_dump(mode="json")
    #                     continue

    #                 if response.status_code == 200:
    #                     if is_search and key_type == "system":
    #                         status.daily_system_search_count += 1
    #                         self.status_db[self.user_id] = status.model_dump(mode="json")
    #                     return response.json()

    #                 elif response.status_code == 404:
    #                     return None

    #             except Exception as e:
    #                 self.logger.error(f"OpenAlex request failed for key {key_type}: {e}")
    #                 continue

    #     return None

    async def _request_with_health_check(
        self, url: str, params: dict, is_search: bool = False
    ) -> Optional[dict]:
        """
        Core execution engine that monitors API health and credit consumption.
        """
        self.logger.info(f"🕵️‍♂️ [OpenAlex HTTP] Iniciando petición a: {url}")
        status = self._get_status()

        configs_db = self.db.dict("user_adapter_configs")
        user_configs = configs_db.get(self.user_id, {})
        openalex_config = user_configs.get(self.name, {})
        personal_api_key = openalex_config.get("personal_api_key")

        keys_to_try = []

        use_personal_key = openalex_config.get("use_personal_key", True)

        has_usable_personal_key = (
            use_personal_key  # <-- 1. El usuario quiere usarla
            and personal_api_key  # <-- 2. La llave existe
            and status.personal_key_active  # <-- 3. La llave no está baneada/agotada
        )

        if has_usable_personal_key:
            keys_to_try.append(("personal", personal_api_key))
            self.logger.info("🔑 [OpenAlex HTTP] Llave personal detectada y encolada.")

        if not is_search:
            for k in self.config.system_keys:
                keys_to_try.append(("system", k))
        else:
            if not personal_api_key or self.config.allow_system_fallback:
                for k in self.config.system_keys:
                    keys_to_try.append(("system", k))

        self.logger.info(
            f"🔄 [OpenAlex HTTP] Total de llaves a intentar: {len(keys_to_try)}"
        )

        for key_type, key_value in keys_to_try:
            if is_search and key_type == "system":
                if status.daily_system_search_count >= self.config.daily_search_limit:
                    self.logger.warning(
                        f"🛑 [OpenAlex HTTP] Límite diario del sistema alcanzado ({status.daily_system_search_count})."
                    )
                    continue

            current_params = params.copy()
            current_params["api_key"] = key_value

            safe_key = f"{key_value[:5]}***" if key_value else "None"
            self.logger.info(
                f"🚀 [OpenAlex HTTP] Ejecutando GET. Tipo de llave: '{key_type}', Llave usada: {safe_key}"
            )

            async with httpx.AsyncClient(timeout=20.0) as client:
                try:
                    response = await client.get(url, params=current_params)
                    self.logger.info(
                        f"📥 [OpenAlex HTTP] Respuesta recibida. Status Code: {response.status_code}"
                    )

                    print(
                        f"📦 [OpenAlex HTTP] RAW RESPONSE BODY:\n{response.text[:2000]}"
                    )

                    remaining = int(
                        response.headers.get("X-RateLimit-Remaining", 100000)
                    )

                    if key_type == "personal" and (
                        remaining <= 0 or response.status_code in (401, 403, 429)
                    ):
                        self.logger.error(
                            f"⚠️ [OpenAlex HTTP] Llave personal rechazada. Status: {response.status_code}"
                        )
                        status.personal_key_active = False
                        self.status_db[self.user_id] = status.model_dump(mode="json")
                        continue

                    if response.status_code == 200:
                        if is_search and key_type == "system":
                            status.daily_system_search_count += 1
                            self.status_db[self.user_id] = status.model_dump(
                                mode="json"
                            )
                        return response.json()

                    elif response.status_code == 404:
                        self.logger.warning(
                            "⚠️ [OpenAlex HTTP] Error 404: No encontrado."
                        )
                        return None
                    else:
                        self.logger.error(
                            f"❌ [OpenAlex HTTP] Error {response.status_code}. Detalle: {response.text}"
                        )

                except Exception as e:
                    self.logger.error(
                        f"💥 [OpenAlex HTTP] Excepción de Red o Timeout al contactar OpenAlex: {str(e)}",
                        exc_info=True,
                    )
                    continue

        self.logger.error("☠️ [OpenAlex HTTP] Proceso abortado. Retornando None.")
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
            max_index = max(
                [pos for positions in inverted_index.values() for pos in positions]
            )
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

        institutions = list(
            {
                inst["display_name"]
                for a in data.get("authorships", [])
                for inst in a.get("institutions", [])
                if inst.get("display_name")
            }
        )

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
            institutions=institutions,
        )

        # async def search_by_text(self, query: str, limit: int = 10) -> List[GlobalDocumentMeta]:
        """
        Restricted text search operation. Subject to daily user quotas.
        """
        params = {"search": query, "per-page": limit}
        data = await self._request_with_health_check(
            self.config.base_url, params, is_search=True
        )

        if not data:
            return []

        results = []
        for item in data.get("results", []):
            doi_url = item.get("doi")
            if not doi_url:
                continue

            institutions = list(
                {
                    inst["display_name"]
                    for a in item.get("authorships", [])
                    for inst in a.get("institutions", [])
                    if inst.get("display_name")
                }
            )

            results.append(
                GlobalDocumentMeta(
                    doi=doi_url.replace("https://doi.org/", ""),
                    title=item.get("title") or "Unknown",
                    authors=[
                        a["author"]["display_name"] for a in item.get("authorships", [])
                    ],
                    year=item.get("publication_year") or 0,
                    file_size=0,
                    storage_uri=self._extract_oa_url(item),
                    source=self.name,
                    abstract=self._reconstruct_abstract(
                        item.get("abstract_inverted_index")
                    ),
                    keywords=[c["display_name"] for c in item.get("concepts", [])[:10]],
                    institutions=institutions,
                )
            )
        return results

    async def search_by_text(
        self, query: str, limit: int = 10
    ) -> List[GlobalDocumentMeta]:
        """
        Restricted text search operation. Subject to daily user quotas.
        """
        self.logger.info(
            f"🔍 [OpenAlex] Iniciando búsqueda de texto: '{query}' (límite: {limit})"
        )
        params = {"search": query, "per-page": limit}

        try:
            data = await self._request_with_health_check(
                self.config.base_url, params, is_search=True
            )

            if not data:
                self.logger.warning(
                    "⚠️ [OpenAlex] La búsqueda devolvió None (Vacío). Revisa logs superiores."
                )
                return []

            items = data.get("results", [])
            self.logger.info(
                f"📄 [OpenAlex] La API devolvió {len(items)} resultados crudos. Iniciando mapeo..."
            )

            results = []
            for item in items:
                try:
                    # 1. EVALUACIÓN DE IDENTIDAD (El Cambio Clave del MVP)
                    doi_url = item.get("doi")

                    if doi_url:
                        # Tiene DOI oficial, lo limpiamos y lo marcamos como válido
                        final_doi = doi_url.replace("https://doi.org/", "")
                        is_official = True
                    else:
                        # NO tiene DOI. Rescatamos el ID de OpenAlex para no perder el paper
                        oa_id = item.get("id")
                        if not oa_id:
                            continue  # Si no tiene ni DOI ni ID de OpenAlex, es basura
                        final_doi = oa_id.replace("https://openalex.org/", "openalex:")
                        is_official = False

                    # 2. EXTRACCIÓN DE METADATOS BÁSICOS (Solución a variables no definidas)
                    title = item.get("title")
                    if not title:
                        continue  # Un paper sin título no nos sirve

                    authors = []
                    for a in item.get("authorships") or []:
                        author_name = a.get("author", {}).get("display_name")
                        if author_name:
                            authors.append(author_name)

                    if not authors:
                        continue  # Requerimos al menos un autor

                    institutions = list(
                        {
                            inst.get("display_name", "Unknown")
                            for a in item.get("authorships", []) or []
                            for inst in a.get("institutions", []) or []
                            if inst.get("display_name")
                        }
                    )

                    raw_concepts = item.get("concepts") or []
                    keywords = [
                        c.get("display_name")
                        for c in raw_concepts[:10]
                        if isinstance(c, dict) and c.get("display_name")
                    ]

                    # 3. CREACIÓN DEL MODELO CON LA NUEVA BANDERA
                    doc = GlobalDocumentMeta(
                        doi=final_doi,
                        is_official_doi=is_official,  # <-- Inyectamos la variable del Bloque 1
                        title=title,
                        authors=authors,
                        year=item.get("publication_year"),
                        file_size=0,
                        storage_uri=self._extract_oa_url(item),
                        source=self.name,
                        abstract=self._reconstruct_abstract(
                            item.get("abstract_inverted_index")
                        ),
                        keywords=keywords,
                        institutions=institutions,
                    )
                    results.append(doc)

                except Exception as parse_error:
                    self.logger.error(
                        f"⚠️ [OpenAlex] Falló parseo de un documento. Error: {parse_error}. ID Item: {item.get('id')}"
                    )
                    continue

            self.logger.info(
                f"✅ [OpenAlex] Búsqueda finalizada con éxito. Devolviendo {len(results)} documentos válidos."
            )
            return results

        except Exception as e:
            # Si el error es masivo, lo logueamos antes de que el Orchestrator lo calle
            self.logger.error(
                f"🚨 [OpenAlex] Excepción fatal inesperada en search_by_text: {str(e)}",
                exc_info=True,
            )
            raise e

    @classmethod
    def get_config_state(
        cls, user_id: str, db: Any, settings: Optional[Settings] = None
    ) -> Dict[str, Any]:
        """
        Retrieves internal system trackers specific to OpenAlex.
        """
        status_db = db.dict("openalex_user_status")
        state = status_db.get(user_id)

        # Si el usuario es nuevo y no ha buscado nada, su estado es None.
        # Lo inicializamos al vuelo para que el frontend no reciba un objeto vacío.
        if not state:
            state = OpenAlexUserStatus(user_id=user_id).model_dump(mode="json")

        # AQUÍ inyectamos el límite de la configuración dinámicamente,
        # sin ensuciar el router genérico.
        if settings:
            state["total_system_search_count"] = (
                settings.data_sources.openalex.daily_search_limit
            )

        return state

    @classmethod
    def apply_config_side_effects(
        cls, user_id: str, config: OpenAlexConfig, db: Any
    ) -> None:
        """
        Updates internal system trackers specific to OpenAlex when a new configuration is provided.
        """

        status_db = db.dict("openalex_user_status")
        status_data = status_db.get(user_id)

        if status_data:
            status = OpenAlexUserStatus.model_validate(status_data)
            status.personal_key_active = True
            status_db[user_id] = status.model_dump(mode="json")
        else:
            new_status = OpenAlexUserStatus(user_id=user_id, personal_key_active=True)
            status_db[user_id] = new_status.model_dump(mode="json")
