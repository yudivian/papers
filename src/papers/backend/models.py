from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class DownloadStatus(str, Enum):
    """
    Defines the discrete lifecycle stages of the asynchronous ingestion process.
    """
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class User(BaseModel):
    """
    Persistence schema for researcher identity and resource management.

    This model is used by the security layer to enforce storage quotas 
    and track the timestamp of the researcher's first interaction.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., description="Unique persistent identifier for the user.")
    byte_quota: int = Field(..., description="Maximum physical storage allocation in bytes.")
    used_bytes: int = Field(default=0, description="Real-time calculated disk footprint.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

class KnowledgeBase(BaseModel):
    """
    Logical grouping for research assets within a user workspace.

    Utilizes a list-pointer pattern to associate documents with projects 
    without duplicating the heavy document metadata or physical files.
    """
    model_config = ConfigDict(from_attributes=True)

    kb_id: str = Field(..., description="Unique workspace identifier.")
    owner_id: str = Field(..., description="The user_id of the workspace owner.")
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None)
    note: Optional[str] = Field(None)
    document_ids: List[str] = Field(
        default_factory=list, 
        description="Collection of DOIs linked to this project."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class GlobalDocumentMeta(BaseModel):
    """
    The authoritative metadata record for an academic document.

    Stores the verified bibliographic data and the internal storage URI. 
    Field names and types are aligned with the OpenAlex and Crossref standards.
    """
    model_config = ConfigDict(from_attributes=True)

    doi: str = Field(..., description="Standard Digital Object Identifier.")
    title: str
    authors: List[str] = Field(default_factory=list)
    year: int
    file_size: int = Field(..., description="Validated physical file size in bytes.")
    storage_uri: str = Field(..., description="Internal path to the binary asset.")
    mime_type: str = Field(default="application/pdf")
    file_extension: str = Field(default=".pdf")
    source: str = Field(default="openalex")
    abstract: Optional[str] = Field(None)
    keywords: List[str] = Field(default_factory=list)
    institutions: List[str] = Field(default_factory=list)

class DownloadRequest(BaseModel):
    """
    Internal tracking record for asynchronous worker tasks.
    """
    model_config = ConfigDict(from_attributes=True)

    ticket_id: str = Field(..., description="Unique polling identifier.")
    user_id: str = Field(...)
    kb_id: str = Field(..., description="Target KB for document linkage.")
    doi: str = Field(..., description="DOI queued for acquisition.")
    status: DownloadStatus = Field(default=DownloadStatus.PENDING)
    error_message: Optional[str] = Field(None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SearchQuery(BaseModel):
    """
    Request schema for natural language semantic search operations.
    """
    text: str = Field(..., min_length=3)
    kb_id: Optional[str] = Field(None)
    limit: int = Field(default=10, ge=1, le=50)
    
class UserAdapterRegistry(BaseModel):
    """
    Audit log of user-source interactions for lazy initialization.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(...)
    active_adapters: List[str] = Field(default_factory=list)
    last_interaction: Dict[str, datetime] = Field(default_factory=dict)

class OpenAlexUserStatus(BaseModel):
    """
    Detailed state management for the OpenAlex integration.

    Tracks personal API key health and enforces daily system search pools.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(...)
    personal_api_key: Optional[str] = Field(None)
    personal_key_active: bool = Field(default=True)
    daily_system_search_count: int = Field(default=0)
    last_reset: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))