"""
Authentication and Provisioning Router.

Handles user login and Just-In-Time (JIT) provisioning for new users.
"""
from fastapi import APIRouter, Header, Depends
from beaver import BeaverDB

from papers.backend.deps import get_db, get_settings
from papers.backend.config import Settings
from papers.backend.models import User, KnowledgeBase

router = APIRouter()

@router.post("/login")
async def login_and_provision(
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    users_db = db.dict("users")
    
    # 1. Si el usuario ya existe, le damos la bienvenida y no tocamos nada
    if x_user_id in users_db:
        return {"status": "ok", "message": "Existing user authenticated"}

    # 2. Si es nuevo, lo aprovisionamos
    quota_bytes = settings.quotas.user_logical_limit_gb * (1024 ** 3)
    new_user = User(
        user_id=x_user_id,
        byte_quota=quota_bytes,
        used_bytes=0,
        metadata={"provisioned_via": "auth_login"}
    )
    users_db[x_user_id] = new_user.model_dump(mode="json")

    # 3. Le regalamos su primera Knowledge Base ("My Library")
    kbs_db = db.dict("knowledge_bases")
    default_kb_id = f"default-{x_user_id}"
    
    default_kb = KnowledgeBase(
        kb_id=default_kb_id,
        owner_id=x_user_id,
        name=settings.app.initial_kb_name,
        description=settings.app.initial_kb_description
    )
    kbs_db[default_kb_id] = default_kb.model_dump(mode="json")

    return {"status": "provisioned", "message": "New user provisioned successfully"}