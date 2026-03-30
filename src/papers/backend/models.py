from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class DownloadStatus(str, Enum):
    """
    Represent the lifecycle stages of a paper acquisition process.
    """
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class User(BaseModel):
    """
    Representation of a researcher within the system.
    
    Designed to be stored in a BeaverDB dictionary for $O(1)$ access 
    during Just-in-Time provisioning and quota validation.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., description="Unique external identifier for the user")
    byte_quota: int = Field(..., description="Maximum allowed storage in bytes")
    used_bytes: int = Field(default=0, description="Current accumulated storage consumption")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Flexible identity provider data")

class KnowledgeBase(BaseModel):
    """
    A logical grouping of research documents, acting as a virtual directory.
    
    Stored in a BeaverDB dictionary to manage project hierarchies without 
    duplicating underlying physical files.
    """
    model_config = ConfigDict(from_attributes=True)

    kb_id: str = Field(..., description="Unique identifier for the knowledge base")
    owner_id: str = Field(..., description="Reference to the User who owns this collection")
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="Detailed purpose of the research project")
    note: Optional[str] = Field(None, description="General research annotations for this collection")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class GlobalDocumentMeta(BaseModel):
    """
    The master metadata record for a unique academic paper.
    
    This model is stored in a BeaverDB dictionary. The semantic embedding 
    (abstract) is deliberately excluded here, as it is managed directly by 
    BeaverDB's Document object in the vector collection.
    """
    model_config = ConfigDict(from_attributes=True)

    doi: str = Field(..., description="Digital Object Identifier acting as the primary key")
    title: str
    authors: List[str] = Field(default_factory=list)
    year: int
    file_size: int = Field(..., description="Physical size of the PDF in bytes")
    storage_uri: str = Field(..., description="Internal URI to locate the file via storage adapters")
    source: str = Field(default="openalex", description="Origin of the document metadata")
    abstract: Optional[str] = Field(None, description="Resumen completo reconstruido del paper")
    keywords: List[str] = Field(default_factory=list, description="Top 10 conceptos o palabras clave")
    institutions: List[str] = Field(default_factory=list, description="Instituciones únicas de los autores")

class KnowledgeBaseEntry(BaseModel):
    """
    The associative link between a GlobalDocumentMeta and a KnowledgeBase.
    
    Stored in a BeaverDB dictionary to map context and specific notes 
    without duplicating the global metadata or vectors.
    """
    model_config = ConfigDict(from_attributes=True)

    kb_id: str = Field(..., description="Target knowledge base identifier")
    doi: str = Field(..., description="Reference to the global document")
    added_at: datetime = Field(default_factory=datetime.utcnow)
    note: Optional[str] = Field(None, description="Researcher's notes for this paper in this specific context")

class DownloadRequest(BaseModel):
    """
    Asynchronous task tracking for the Castor worker.
    """
    model_config = ConfigDict(from_attributes=True)

    ticket_id: str = Field(..., description="Tracking ID for frontend polling")
    user_id: str = Field(..., description="Requester identifier")
    kb_id: str = Field(..., description="Target collection for the final link")
    doi: str = Field(..., description="Target DOI to be acquired")
    status: DownloadStatus = Field(default=DownloadStatus.PENDING)
    error_message: Optional[str] = Field(None, description="Detailed failure reason if applicable")
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SearchQuery(BaseModel):
    """
    Input schema for multilingual semantic search requests.
    """
    text: str = Field(..., min_length=3)
    kb_id: Optional[str] = Field(None, description="Optional filter to search within a specific project")
    limit: int = Field(default=10, ge=1, le=50)
    
class UserAdapterRegistry(BaseModel):
    """
    Tracks which data adapters a user has initialized or interacted with.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., description="Unique identifier of the user who owns this registry")
    active_adapters: List[str] = Field(default_factory=list, description="List of initialized adapter names")
    last_interaction: Dict[str, datetime] = Field(default_factory=dict, description="Timestamp of the last activity per adapter")

class OpenAlexUserStatus(BaseModel):
    """
    Satellite state for OpenAlex-specific metadata, including personal keys and search quotas.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(..., description="Unique identifier of the user")
    personal_api_key: Optional[str] = Field(None, description="User-provided OpenAlex API key")
    personal_key_active: bool = Field(default=True, description="Health status of the personal API key")
    daily_system_search_count: int = Field(default=0, description="Number of text searches using the system pool")
    last_reset: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp for the next daily quota renewal cycle"
    )