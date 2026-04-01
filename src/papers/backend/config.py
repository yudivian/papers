import yaml
from typing import List, Optional, Type, Any
from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

class ServerConfig(BaseModel):
    """
    Configuration for the FastAPI web server instance.
    """
    host: str = "0.0.0.0"
    port: int = 8000

class AppConfig(BaseModel):
    """
    General application environment, logging, and provisioning settings.
    """
    environment: str = "development"
    log_level: str = "INFO"
    server: ServerConfig = Field(default_factory=ServerConfig)
    initial_kb_name: str = Field(default="My Library")
    initial_kb_description: str = Field(default="System provisioned initial workspace.")

class DatabaseConfig(BaseModel):
    """
    Persistence settings for metadata and vector storage.
    """
    file: str = "papers.db"

class LocalStorageConfig(BaseModel):
    """
    Settings for the local file system storage provider.
    """
    base_path: str = "./storage/pdfs"

class StorageConfig(BaseModel):
    """
    Storage orchestration settings.
    """
    selected: str = "local"
    local: LocalStorageConfig = Field(default_factory=LocalStorageConfig)

class OpenAlexConfig(BaseModel):
    """
    Configuration for the OpenAlex data source API.
    """
    base_url: str = Field(default="https://api.openalex.org/works")
    system_keys: List[str] = Field(default_factory=list)
    daily_search_limit: int = Field(default=10, ge=0)    
    allow_system_fallback: bool = Field(default=True)

class DataSourcesConfig(BaseModel):
    """
    Settings for external data acquisition and search priority.
    """
    priority: List[str] = Field(default_factory=lambda: ["cache", "openalex"])
    openalex: OpenAlexConfig

class QuotasConfig(BaseModel):
    """
    Resource usage limits for users and workers.
    """
    user_logical_limit_gb: int = 5
    max_concurrent_tasks: int = 3

class SearchConfig(BaseModel):
    """
    Semantic search engine and embedding model settings.
    """
    model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

class Settings(BaseSettings):
    """
    Main settings class that aggregates all configuration blocks.
    """
    app: AppConfig
    database: DatabaseConfig
    storage: StorageConfig
    data_sources: DataSourcesConfig
    quotas: QuotasConfig
    search: SearchConfig

    @classmethod
    def load_from_yaml(cls, yaml_path: str = "config.yaml") -> "Settings":
        """
        Loads and validates configuration from a physical YAML file.
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found at: {yaml_path}")

        with path.open("r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        return cls(**config_data)