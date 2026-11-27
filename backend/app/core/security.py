"""JWT issuance and Bearer token verification into RLSContext."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.db import RLSContext

_bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(ctx: RLSContext, expires_minutes: int | None = None) -> str:
    """Sign a JWT containing verified organization and clearance claims."""
    ttl = expires_minutes or settings.jwt_expire_minutes
    now = datetime.now(UTC)
    payload = {
        "sub": str(ctx.user_id),
        "org_id": str(ctx.org_id),
        "clearance_level": ctx.clearance_level,
        "department": ctx.department,
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
    """FastAPI dependency extracting RLSContext from Authorization Bearer token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer authorization token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_access_token(credentials.credentials)
