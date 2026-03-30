from fastapi import Header, Depends
from beaver import BeaverDB
from papers.backend.models import User, KnowledgeBase
from papers.backend.config import Settings

def get_settings() -> Settings:
    """
    Provide a cached or newly instantiated Settings object.
    
    This acts as a FastAPI dependency to ensure configuration is loaded 
    and injected safely into other route dependencies without redundant 
    I/O operations on the YAML file.
    
    Returns:
        A validated Settings instance containing application quotas and configurations.
    """
    return Settings.load_from_yaml()

def get_db() -> BeaverDB:
    """
    Yield a thread-safe instance of the BeaverDB client.
    
    This dependency abstracts the database connection lifecycle, allowing 
    FastAPI to manage the connection context per request.
    
    Returns:
        An active BeaverDB instance connected to the configured storage file.
    """
    return BeaverDB("papers.db")

async def get_current_user(
    x_user_id: str = Header(..., alias="X-User-ID"),
    settings: Settings = Depends(get_settings),
    db: BeaverDB = Depends(get_db)
) -> User:
    """
    Intercept incoming requests to validate and provision user identity dynamically.
    
    This function implements the Just-in-Time (JIT) provisioning architecture. 
    It queries the persistent 'users' dictionary in BeaverDB. If the identifier 
    is absent, it synthesizes a new User record based on system quotas, provisions 
    an initial Knowledge Base to prevent cold-start UI issues, and persists both 
    entities before granting request access.
    
    Args:
        x_user_id: The unique identity string extracted from the HTTP headers.
        settings: The injected application configuration containing quota limits.
        db: The injected BeaverDB client instance.
        
    Returns:
        A fully hydrated User Pydantic model representing the active session.
    """
    users_db = db.dict("users")
    
    if x_user_id in users_db:
        user_data = users_db[x_user_id]
        return User.model_validate(user_data) if isinstance(user_data, dict) else user_data

    quota_bytes = settings.quotas.user_logical_limit_gb * (1024 ** 3)
    
    new_user = User(
        user_id=x_user_id,
        byte_quota=quota_bytes,
        used_bytes=0,
        metadata={"provisioned_via": "jit_gatekeeper"}
    )
    
    users_db[x_user_id] = new_user.model_dump(mode="json")

    kbs_db = db.dict("knowledge_bases")
    default_kb_id = f"default-{x_user_id}"
    
    default_kb = KnowledgeBase(
        kb_id=default_kb_id,
        owner_id=x_user_id,
        name="My Library",
        description="System provisioned initial workspace.",
        note="Automatically generated during first login."
    )
    
    kbs_db[default_kb_id] = default_kb.model_dump(mode="json")

    return new_user