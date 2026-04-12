"""
Domain models and persistence schemas for the Papers AI Engine.

This module defines the foundational data structures utilized across the
application. All classes inherit from Pydantic's BaseModel to enforce
strict type validation and facilitate seamless serialization to and from
the BeaverDB dictionary storage.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class DownloadStatus(str, Enum):
    """
    Enumeration representing the discrete lifecycle stages of an ingestion task.
    """

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class User(BaseModel):
    """
    Entity representing a researcher within the system.

    Used by the security and dependency injection layers to enforce
    logical storage quotas and track aggregated system usage.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., description="Unique external identifier for the user.")
    byte_quota: int = Field(
        ..., description="Maximum physical storage allocation in bytes."
    )
    used_bytes: int = Field(
        default=0, description="Real-time calculated disk footprint."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Flexible provider attributes."
    )


class KnowledgeBase(BaseModel):
    """
    Logical grouping mechanism for research assets within a user workspace.

    Utilizes a list-pointer pattern (document_ids) to associate documents
    with specific projects without duplicating the heavy global metadata
    records or the underlying physical files.
    """

    model_config = ConfigDict(from_attributes=True)

    kb_id: str = Field(..., description="Unique workspace identifier.")
    owner_id: str = Field(..., description="The user_id of the workspace owner.")
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(
        None, description="Detailed purpose of the research project."
    )
    note: Optional[str] = Field(None, description="General research annotations.")
    document_ids: List[str] = Field(
        default_factory=list, description="Collection of DOIs linked to this project."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GlobalDocumentMeta(BaseModel):
    """
    The authoritative and format-agnostic metadata record for an academic document.

    Stores verified bibliographic data and the internal storage URI. The source
    attribute defaults to 'unknown' to ensure neutrality when new data adapters
    are integrated into the ecosystem.
    """

    model_config = ConfigDict(from_attributes=True)

    doi: str = Field(..., description="Standard Digital Object Identifier.")
    is_official_doi: bool = True
    title: str
    authors: List[str] = Field(default_factory=list)
    year: int
    file_size: int = Field(..., description="Validated physical file size in bytes.")
    storage_uri: str = Field(..., description="Internal path to the binary asset.")
    mime_type: str = Field(
        default="application/octet-stream", description="MIME media type of the asset."
    )
    file_extension: str = Field(default="", description="File extension of the asset.")
    source: str = Field(
        default="unknown", description="Origin provider of the metadata."
    )
    abstract: Optional[str] = Field(
        None, description="Full reconstructed paper abstract."
    )
    keywords: List[str] = Field(
        default_factory=list, description="Extracted semantic concepts."
    )
    institutions: List[str] = Field(
        default_factory=list, description="Unique author affiliations."
    )
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp indicating when the document was added to the system.",
    )


class DownloadRequest(BaseModel):
    """
    Internal tracking record for asynchronous worker tasks.

    Allows the frontend polling mechanism to retrieve the real-time status
    and error traces of ongoing document ingestion workloads.
    """

    model_config = ConfigDict(from_attributes=True)

    ticket_id: str = Field(..., description="Unique polling identifier.")
    user_id: str = Field(..., description="Requester identifier.")
    kb_id: str = Field(..., description="Target KB for document linkage.")
    doi: str = Field(..., description="DOI queued for acquisition.")
    title: str = Field(..., description="Human-readable title of the paper.")
    status: DownloadStatus = Field(default=DownloadStatus.PENDING)
    error_message: Optional[str] = Field(
        None, description="Detailed failure reason if applicable."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SearchQuery(BaseModel):
    """
    Request schema for natural language semantic search operations.
    """

    text: str = Field(..., min_length=3)
    kb_id: Optional[str] = Field(
        None, description="Optional project filter constraint."
    )
    limit: int = Field(default=10, ge=1, le=50)


class UserAdapterRegistry(BaseModel):
    """
    Audit log of user-source interactions for lazy initialization strategies.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., description="Unique identifier of the owner.")
    active_adapters: List[str] = Field(
        default_factory=list, description="Initialized adapter names."
    )
    last_interaction: Dict[str, datetime] = Field(
        default_factory=dict, description="Last activity timestamps."
    )


class OpenAlexUserStatus(BaseModel):
    """
    Internal system state tracking for OpenAlex usage constraints.

    This model strictly tracks read-only metrics and health flags, separating
    them from the user-editable configurations defined in the data sources layer.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., description="Unique identifier of the user.")
    personal_key_active: bool = Field(
        default=True, description="System health status of the user's personal key."
    )
    daily_system_search_count: int = Field(
        default=0, description="Number of searches using the shared system pool."
    )
    total_system_search_count: int = Field(
        default=10, description="Total cumulative searches using system pool."
    )
    last_reset: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp for the next daily quota renewal cycle.",
    )


class CoreUserStatus(BaseModel):
    """
    Internal system state tracking for CORE API usage constraints.

    This model strictly tracks read-only metrics and health flags, separating
    them from the user-editable configurations defined in the data sources layer.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., description="Unique identifier of the user.")
    personal_key_active: bool = Field(
        default=False,
        description="User intent flag: True if the user has configured a personal key.",
    )
    is_key_invalid: bool = Field(
        default=False,
        description="Health flag: True if the CORE API recently rejected the personal key (HTTP 401/403).",
    )
    daily_system_search_count: int = Field(
        default=0, description="Number of searches using the shared system pool."
    )
    total_system_search_count: int = Field(
        default=0, description="Total cumulative searches using system pool."
    )
    last_reset: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp for the next daily quota renewal cycle.",
    )


class LoginRequest(BaseModel):
    """
    Data model for receiving the exact credentials sent by the frontend.
    """
    user_id: str
    password: str
    
class OrcidExternalId(BaseModel):
    """Represents a generic external ID (DOI, ISSN, EID, Scopus ID, etc.)"""
    type: str         
    value: str        
    url: Optional[str] = None # 

class OrcidAffiliation(BaseModel):
    """Represents emplpyment, education or qualifications."""
    organization: str
    role: str
    start_year: Optional[str] = None
    end_year: Optional[str] = None

class OrcidWork(BaseModel):
    """Represents an individual researcher publication."""
    title: str
    type: str  
    publication_year: Optional[str] = None
    
    external_ids: List[OrcidExternalId] = Field(default_factory=list)
    
    url: Optional[str] = None
    journal_title: Optional[str] = None
    source: Optional[str] = None      
    citation: Optional[str] = None    
    
    created_date: Optional[int] = None
    last_modified_date: Optional[int] = None


class OrcidStatus(BaseModel):
    """Documents representing orcid information for each user."""
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    orcid_id: str
    is_enabled: bool = True
    payload: Dict[str, Any] = Field(default_factory=dict)
    orcid_last_modified: Optional[int] = None 
    local_last_checked: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class OrcidProfileResponse(BaseModel):
    """Final user orcid information from payload to render in frontend"""
    sync_status: str             
    last_updated: datetime        
    
    orcid_id: str
    full_name: str
    credit_name: Optional[str] = None
    biography: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    
    researcher_urls: List[Dict[str, str]] = Field(default_factory=list) 
    
    external_ids: List[OrcidExternalId] = Field(default_factory=list) 
    
    employments: List[OrcidAffiliation] = Field(default_factory=list)
    educations: List[OrcidAffiliation] = Field(default_factory=list)
    qualifications: List[OrcidAffiliation] = Field(default_factory=list)
    
    works: List[OrcidWork] = Field(default_factory=list)