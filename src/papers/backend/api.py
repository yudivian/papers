"""
Master routing module for the Papers API.

This module aggregates all domain-specific routers into a single, unified 
APIRouter instance. It enforces consistent URL prefixing and OpenAPI tagging 
across the entire application boundary, keeping the main application entrypoint 
clean and highly cohesive.
"""

from fastapi import APIRouter

from papers.backend.routers import (
    users,
    kbs,
    discovery,
    ingestion,
    documents,
    sources,
    auth
)

api_router = APIRouter()

api_router.include_router(
    users.router, 
    prefix="/users", 
    tags=["Identity and Quotas"]
)

api_router.include_router(
    kbs.router, 
    prefix="/kbs", 
    tags=["Knowledge Bases"]
)

api_router.include_router(
    discovery.router, 
    prefix="/discovery", 
    tags=["Discovery and Search"]
)

api_router.include_router(
    ingestion.router, 
    prefix="/ingestion", 
    tags=["Asynchronous Ingestion"]
)

api_router.include_router(
    documents.router, 
    prefix="/documents", 
    tags=["Document Library"]
)

api_router.include_router(
    sources.router, 
    prefix="/sources", 
    tags=["Data Sources"]
)

api_router.include_router(
    auth.router, 
    prefix="/auth", 
    tags=["Authentication and Provisioning"]
)