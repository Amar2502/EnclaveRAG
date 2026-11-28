"""Password hashing (Argon2), JWT issuance, and live token revocation checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash

from app.core.config import settings
from app.core.db import RLSContext, get_db_pool

_bearer_scheme = HTTPBearer(auto_error=False)
_password_hasher = PasswordHash.recommended()


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against its stored Argon2id hash."""
    return _password_hasher.verify(plain_password, password_hash)


def create_access_token(ctx: RLSContext, expires_minutes: int | None = None) -> str:
    """Sign a JWT containing verified organization, clearance, and revocation claims."""
    ttl = expires_minutes or settings.jwt_expire_minutes
    now = datetime.now(UTC)
    payload = {
        "sub": str(ctx.user_id),
        "org_id": str(ctx.org_id),
        "clearance_level": ctx.clearance_level,
        "department": ctx.department,
        "is_org_admin": ctx.is_org_admin,
        "tv": ctx.token_version,
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_access_token(token: str) -> RLSContext:
    """Decode and validate a JWT into an immutable RLSContext."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "org_id", "clearance_level", "exp"]},
        )
        return RLSContext(
            user_id=UUID(str(payload["sub"])),
            org_id=UUID(str(payload["org_id"])),
            clearance_level=int(payload["clearance_level"]),
            department=str(payload.get("department", "General")),
            is_org_admin=bool(payload.get("is_org_admin", False)),
            token_version=int(payload.get("tv", 1)),
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_rls_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> RLSContext:
    """Extract RLSContext from Bearer token and enforce live active/token_version checks."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer authorization token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claimed = verify_access_token(credentials.credentials)
    pool = get_db_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT org_id, clearance_level, department, is_org_admin, is_active, token_version
            FROM users
            WHERE id = %s
            """,
            (claimed.user_id,),
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    org_id, clearance, department, is_org_admin, is_active, token_version = row
    if not is_active or int(token_version) != claimed.token_version or org_id != claimed.org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked or account deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return RLSContext(
        org_id=org_id,
        user_id=claimed.user_id,
        clearance_level=int(clearance),
        department=str(department),
        is_org_admin=bool(is_org_admin),
        token_version=int(token_version),
    )


async def require_org_admin(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> RLSContext:
    """Ensure the authenticated user holds organization admin privileges."""
    if not ctx.is_org_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization admin privileges required.",
        )
    return ctx
