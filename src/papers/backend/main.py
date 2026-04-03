"""
Main application entrypoint for the Papers Engine REST API.

This module initializes the FastAPI application instance, configures global 
middleware such as CORS for frontend integration, and mounts the primary 
API router containing all domain-specific endpoints.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from papers.backend.api import api_router

app = FastAPI(
    title="Papers AI Engine",
    description="Autonomous Academic Research and Semantic Search API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    """
    Provides a lightweight, unauthenticated endpoint for monitoring 
    application liveliness and network reachability.
    """
    return {"status": "operational", "engine": "papers-ai"}