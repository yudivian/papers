"""
Authentication and Provisioning Router.

Handles user login and Just-In-Time (JIT) provisioning for new users.
"""
from fastapi import APIRouter, Header, Depends
from beaver import BeaverDB

from papers.backend.deps import get_db, get_settings
from papers.backend.config import Settings
from papers.backend.models import User, KnowledgeBase
from papers.backend.models import LoginRequest
from papers.backend.security import authenticate_user
from fastapi import HTTPException, status

router = APIRouter()

# @router.post("/login")
# async def login_and_provision(
#     x_user_id: str = Header(..., alias="X-User-ID"),
#     db: BeaverDB = Depends(get_db),
#     settings: Settings = Depends(get_settings)
# ):
#     users_db = db.dict("users")
    
#     # 1. Si el usuario ya existe, le damos la bienvenida y no tocamos nada
#     if x_user_id in users_db:
#         return {"status": "ok", "message": "Existing user authenticated"}

#     # 2. Si es nuevo, lo aprovisionamos
#     quota_bytes = settings.quotas.user_logical_limit_gb * (1024 ** 3)
#     new_user = User(
#         user_id=x_user_id,
#         byte_quota=quota_bytes,
#         used_bytes=0,
#         metadata={"provisioned_via": "auth_login"}
#     )
#     users_db[x_user_id] = new_user.model_dump(mode="json")

#     # 3. Le regalamos su primera Knowledge Base ("My Library")
#     kbs_db = db.dict("knowledge_bases")
#     default_kb_id = f"default-{x_user_id}"
    
#     default_kb = KnowledgeBase(
#         kb_id=default_kb_id,
#         owner_id=x_user_id,
#         name=settings.app.initial_kb_name,
#         description=settings.app.initial_kb_description
#     )
#     kbs_db[default_kb_id] = default_kb.model_dump(mode="json")

#     return {"status": "provisioned", "message": "New user provisioned successfully"}

"""
Authentication and Provisioning Router.

Handles user login and Just-In-Time (JIT) provisioning for new users.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from beaver import BeaverDB

from papers.backend.deps import get_db, get_settings
from papers.backend.config import Settings
from papers.backend.models import User, KnowledgeBase, LoginRequest
from papers.backend.security import authenticate_user

router = APIRouter()

async def provision_new_user(user_id: str, db: BeaverDB, settings: Settings) -> dict:
    """
    Provisions a new user in the system.
    This function handles the creation of the user profile, role assignment,
    and the initialization of their default Knowledge Base in BeaverDB.
    """
    users_db = db.dict("users")
    
    quota_bytes = settings.quotas.user_logical_limit_gb * (1024 ** 3)
    new_user = User(
        user_id=user_id,
        byte_quota=quota_bytes,
        used_bytes=0,
        metadata={"provisioned_via": "auth_login"}
    )
    users_db[user_id] = new_user.model_dump(mode="json")

    kbs_db = db.dict("knowledge_bases")
    default_kb_id = f"default-{user_id}"
    
    default_kb = KnowledgeBase(
        kb_id=default_kb_id,
        owner_id=user_id,
        name=settings.app.initial_kb_name,
        description=settings.app.initial_kb_description
    )
    kbs_db[default_kb_id] = default_kb.model_dump(mode="json")

    return {"status": "provisioned", "message": "New user provisioned successfully"}


# @router.post("/login")
# async def login(
#     credentials: LoginRequest,
#     db: BeaverDB = Depends(get_db),
#     settings: Settings = Depends(get_settings)
# ):
#     """
#     Authenticates the user and returns their profile.
#     If the authentication succeeds but the user does not exist in the database,
#     it automatically provisions a new account and workspace.
#     """
#     # 1. The Gatekeeper: Validate credentials via security layer
# # 1. The Gatekeeper: Validate credentials via security layer
#     is_authenticated = authenticate_user(credentials.user_id, credentials.password, settings)    
#     if not is_authenticated:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid credentials or unauthorized access."
#         )

#     # 2. Fetch existing user from the database
#     users_db = db.dict("users")
#     if credentials.user_id in users_db:
#         return {"status": "ok", "message": "Existing user authenticated"}

#     # 3. Provisioning pipeline for first-time authenticated users
#     return await provision_new_user(credentials.user_id, db, settings)

from fastapi import APIRouter, Depends, HTTPException, status
from papers.backend.security import verify_ldap, create_access_token

@router.post("/login")
async def login(
    credentials: LoginRequest,
    db: BeaverDB = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """
    Authenticates the user and returns their session token.
    Implements a strict environment branching to keep development frictionless.
    """
    users_db = db.dict("users")

    # ==========================================
    # FLOW 1: PRODUCTION (Strict LDAP)
    # ==========================================
    if settings.app.environment == "production":
        
        profile_data = verify_ldap(credentials.user_id, credentials.password, settings)
        if not profile_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid LDAP credentials"
            )

        # Base JIT Provisioning (Using your unmodified original function)
        if credentials.user_id not in users_db:
            await provision_new_user(credentials.user_id, db, settings)

        # Store LDAP Identity in a completely separate dictionary to avoid coupling
        ldap_db = db.dict("ldap_profiles")
        ldap_db[credentials.user_id] = {
            "user_id": credentials.user_id,
            "full_name": profile_data.get("full_name", ""),
            "department": profile_data.get("department", ""),
            "academic_title": profile_data.get("academic_title", "")
        }
        
        # In production, the token is a secure JWT
        token = create_access_token(credentials.user_id, settings)
        
    # ==========================================
    # FLOW 2: DEVELOPMENT (Unmodified fallback)
    # ==========================================
    else:
        # Pass-through without password check
        if credentials.user_id not in users_db:
            await provision_new_user(credentials.user_id, db, settings)
        
        # In development, the token is just the plain user_id (same behavior as before)
        token = credentials.user_id

    # Return the token under a dedicated key
    return {
        "status": "ok", 
        "message": "User authenticated", 
        "access_token": token, 
        "user_id": credentials.user_id
    }