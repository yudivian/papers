from fastapi import Header, Depends
from papers.backend.config import Settings
import jwt
from datetime import datetime, timedelta, timezone
from ldap3 import Server, Connection, ALL, SUBTREE


def create_access_token(user_id: str, settings: Settings) -> str:
    """
    Creates a cryptographically signed JWT for the user session.
    In production, this string replaces the plaintext user ID in headers.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.security.token_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.security.secret_key, algorithm=settings.security.algorithm)

def verify_ldap(user_id: str, password: str, settings: Settings) -> dict | None:
    """
    Validates credentials against the university LDAP server.
    Returns a dictionary with the extracted profile data if successful, None otherwise.
    """
    try:
        server = Server(settings.ldap.address, get_info=ALL)
        
        # 1. Bind with service account to find the researcher's DN
        conn = Connection(
            server,
            f"cn={settings.ldap.user},{settings.ldap.base_dn}",
            settings.ldap.passwd,
            auto_bind=True
        )

        conn.search(
            search_base=settings.ldap.base_dn,
            search_filter=f"(uid={user_id})",
            search_scope=SUBTREE,
            attributes=['cn', 'sn', 'ou', 'title']
        )

        if not conn.entries:
            return None

        entry = conn.entries[0]
        user_dn = entry.entry_dn

        profile = {
            "full_name": f"{entry.cn} {entry.sn}".strip() if hasattr(entry, 'cn') else user_id,
            "department": str(entry.ou) if hasattr(entry, 'ou') else "",
            "academic_title": str(entry.title) if hasattr(entry, 'title') else ""
        }

        # 2. Second bind to strictly validate the user's real password
        user_conn = Connection(server, user_dn, password, auto_bind=True)
        user_conn.unbind()
        conn.unbind()

        return profile
    except Exception as e:
        print(f"\n🚨 [DEBUG LDAP] Error crítico en la conexión o validación:")
        print(f"🚨 Detalles: {e}\n")
        return None


def dummy_ldap_auth(user_id: str, password: str) -> bool:
    """
    Placeholder for future LDAP integration.
    Currently rejects all access attempts in production until implemented.
    """
    # TODO: Implement actual LDAP connection logic here
    return False


def authenticate_user(user_id: str, password: str, settings: Settings) -> bool:
    """
    Main gatekeeper for user authentication.
    Evaluates the environment to decide whether to apply strict validation
    or bypass it for local development.
    """
    if settings.app.environment == "development":
        # Developer mode bypass
        return True

    # Production mode: requires real verification
    return dummy_ldap_auth(user_id, password)
