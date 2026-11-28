"""Database-backed auth, org registration, invitations, and instant session revocation."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation

from app.core.config import settings
from app.core.db import RLSContext, get_db_pool, scoped_rls_transaction
from app.core.security import create_access_token, hash_password, verify_password


class ConflictError(ValueError):
    """Raised on duplicate organization, email, or active user conflict."""


class AuthenticationError(PermissionError):
    """Raised when login credentials fail or user is inactive."""


class InvalidInvitationError(ValueError):
    """Raised when an invitation token is missing, expired, or already accepted."""


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or f"org-{uuid4().hex[:8]}"


def _hash_invite_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _build_auth_response(ctx: RLSContext, *, org_name: str, email: str, full_name: str, role_title: str) -> dict[str, Any]:
    token = create_access_token(ctx)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": str(ctx.user_id),
            "org_id": str(ctx.org_id),
            "org_name": org_name,
            "email": email,
            "full_name": full_name,
            "role_title": role_title,
            "department": ctx.department,
            "clearance_level": ctx.clearance_level,
            "is_org_admin": ctx.is_org_admin,
        },
    }


async def register_organization(
    *,
    org_name: str,
    full_name: str,
    email: str,
    password: str,
    department: str = "Executive",
) -> dict[str, Any]:
    """Create a new tenant organization and its initial L4 Org Admin user."""
    normalized_email = email.strip().lower()
    slug = _slugify(org_name)
    pw_hash = hash_password(password)
    pool = get_db_pool()

    try:
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO organizations (name, slug)
                VALUES (%s, %s)
                RETURNING id, name
                """,
                (org_name.strip(), slug),
            )
            org_row = await cur.fetchone()
            assert org_row is not None
            org_id, created_org_name = org_row

            await cur.execute(
                """
                INSERT INTO users
                    (org_id, email, full_name, role_title, department,
                     clearance_level, password_hash, is_org_admin, is_active, token_version)
                VALUES (%s, %s, %s, 'Organization Admin', %s, 4, %s, true, true, 1)
                RETURNING id
                """,
                (org_id, normalized_email, full_name.strip(), department.strip(), pw_hash),
            )
            user_row = await cur.fetchone()
            assert user_row is not None
            user_id = user_row[0]
    except UniqueViolation as exc:
        raise ConflictError("Organization name or email is already registered.") from exc

    ctx = RLSContext(
        org_id=org_id,
        user_id=user_id,
        clearance_level=4,
        department=department.strip(),
        is_org_admin=True,
        token_version=1,
    )
    return _build_auth_response(
        ctx,
        org_name=created_org_name,
        email=normalized_email,
        full_name=full_name.strip(),
        role_title="Organization Admin",
    )


async def authenticate_user(*, email: str, password: str) -> dict[str, Any]:
    """Authenticate an active user with Argon2 password verification."""
    normalized_email = email.strip().lower()
    pool = get_db_pool()

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT u.id, u.org_id, o.name, u.email, u.full_name, u.role_title,
                   u.department, u.clearance_level, u.password_hash,
                   u.is_org_admin, u.is_active, u.token_version
            FROM users u
            JOIN organizations o ON o.id = u.org_id
            WHERE lower(u.email) = %s
            """,
            (normalized_email,),
        )
        row = await cur.fetchone()

    if row is None or row[8] is None or not verify_password(password, row[8]):
        raise AuthenticationError("Invalid email or password.")
    if not row[10]:
        raise AuthenticationError("Account has been deactivated by your organization admin.")

    ctx = RLSContext(
        org_id=row[1],
        user_id=row[0],
        clearance_level=int(row[7]),
        department=str(row[6]),
        is_org_admin=bool(row[9]),
        token_version=int(row[11]),
    )
    return _build_auth_response(
        ctx,
        org_name=str(row[2]),
        email=str(row[3]),
        full_name=str(row[4]),
        role_title=str(row[5]),
    )


async def revoke_user_sessions(*, org_id: UUID, user_id: UUID) -> bool:
    """Increment token_version to immediately invalidate all existing JWTs for user_id."""
    pool = get_db_pool()
    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE users
            SET token_version = token_version + 1
            WHERE id = %s AND org_id = %s
            RETURNING id
            """,
            (user_id, org_id),
        )
        return (await cur.fetchone()) is not None


async def create_invitation(
    ctx: RLSContext,
    *,
    email: str,
    role_title: str,
    department: str,
    clearance_level: int,
    expires_days: int = 7,
) -> dict[str, Any]:
    """Create a tenant-scoped invitation and return the one-time raw invite token."""
    normalized_email = email.strip().lower()
    pool = get_db_pool()

    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM users WHERE lower(email) = %s", (normalized_email,))
        if await cur.fetchone() is not None:
            raise ConflictError("A user with this email already exists.")

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_invite_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(days=expires_days)

    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO invitations
                (org_id, email, role_title, department, clearance_level,
                 token_hash, invited_by, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (
                ctx.org_id,
                normalized_email,
                role_title.strip(),
                department.strip(),
                clearance_level,
                token_hash,
                ctx.user_id,
                expires_at,
            ),
        )
        row = await cur.fetchone()
        assert row is not None
        invite_id, created_at = row

    base_url = settings.app_base_url.rstrip("/")
    return {
        "id": str(invite_id),
        "org_id": str(ctx.org_id),
        "email": normalized_email,
        "role_title": role_title.strip(),
        "department": department.strip(),
        "clearance_level": clearance_level,
        "expires_at": expires_at.isoformat(),
        "created_at": created_at.isoformat(),
        "invite_token": raw_token,
        "invite_url": f"{base_url}/accept-invite?token={raw_token}",
    }


async def accept_invitation(
    *,
    raw_token: str,
    full_name: str,
    password: str,
) -> dict[str, Any]:
    """Validate an invite token, create the employee account, and return a JWT."""
    token_hash = _hash_invite_token(raw_token.strip())
    pw_hash = hash_password(password)
    pool = get_db_pool()

    try:
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute("SELECT * FROM resolve_pending_invitation(%s)", (token_hash,))
            inv = await cur.fetchone()
            if inv is None:
                raise InvalidInvitationError("Invalid invitation token.")

            inv_id, org_id, org_name, email, role_title, department, clearance, expires_at, accepted_at = inv
            if accepted_at is not None or expires_at <= datetime.now(UTC):
                raise InvalidInvitationError("Invitation has expired or already been used.")

            await cur.execute("SELECT mark_invitation_accepted(%s)", (inv_id,))
            marked = await cur.fetchone()
            if marked is None or not marked[0]:
                raise InvalidInvitationError("Invitation could not be accepted.")

            await cur.execute(
                """
                INSERT INTO users
                    (org_id, email, full_name, role_title, department,
                     clearance_level, password_hash, is_org_admin, is_active, token_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, false, true, 1)
                RETURNING id
                """,
                (org_id, email, full_name.strip(), role_title, department, clearance, pw_hash),
            )
            user_row = await cur.fetchone()
            assert user_row is not None
            user_id = user_row[0]
    except UniqueViolation as exc:
        raise ConflictError("An account with this email already exists.") from exc

    ctx = RLSContext(
        org_id=org_id,
        user_id=user_id,
        clearance_level=int(clearance),
        department=str(department),
        is_org_admin=False,
        token_version=1,
    )
    return _build_auth_response(
        ctx,
        org_name=str(org_name),
        email=str(email),
        full_name=full_name.strip(),
        role_title=str(role_title),
    )


async def list_org_invitations(ctx: RLSContext) -> list[dict[str, Any]]:
    """List invitations strictly within the admin's organization under RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, email, role_title, department, clearance_level,
                   expires_at, accepted_at, created_at
            FROM invitations
            ORDER BY created_at DESC
            """
        )
        rows = await cur.fetchall()

    return [
        {
            "id": str(row[0]),
            "email": row[1],
            "role_title": row[2],
            "department": row[3],
            "clearance_level": row[4],
            "expires_at": row[5].isoformat(),
            "accepted_at": row[6].isoformat() if row[6] else None,
            "created_at": row[7].isoformat(),
        }
        for row in rows
    ]


async def list_org_users(ctx: RLSContext) -> list[dict[str, Any]]:
    """List employees belonging strictly to the admin's organization."""
    pool = get_db_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, email, full_name, role_title, department,
                   clearance_level, is_org_admin, is_active, token_version, created_at
            FROM users
            WHERE org_id = %s
            ORDER BY clearance_level DESC, created_at ASC
            """,
            (ctx.org_id,),
        )
        rows = await cur.fetchall()

    return [
        {
            "id": str(row[0]),
            "email": row[1],
            "full_name": row[2],
            "role_title": row[3],
            "department": row[4],
            "clearance_level": row[5],
            "is_org_admin": row[6],
            "is_active": row[7],
            "token_version": row[8],
            "created_at": row[9].isoformat(),
        }
        for row in rows
    ]


async def update_org_user(
    ctx: RLSContext,
    *,
    target_user_id: UUID,
    clearance_level: int | None = None,
    department: str | None = None,
    role_title: str | None = None,
    is_org_admin: bool | None = None,
    is_active: bool | None = None,
) -> dict[str, Any] | None:
    """Update an employee's permissions and immediately revoke existing JWTs."""
    if target_user_id == ctx.user_id and (is_active is False or is_org_admin is False):
        raise ValueError("Admins cannot deactivate or remove admin rights from themselves.")

    pool = get_db_pool()
    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE users
            SET clearance_level = COALESCE(%s, clearance_level),
                department = COALESCE(%s, department),
                role_title = COALESCE(%s, role_title),
                is_org_admin = COALESCE(%s, is_org_admin),
                is_active = COALESCE(%s, is_active),
                token_version = token_version + 1
            WHERE id = %s AND org_id = %s
            RETURNING id, email, full_name, role_title, department,
                      clearance_level, is_org_admin, is_active, token_version, created_at
            """,
            (
                clearance_level,
                department.strip() if department else None,
                role_title.strip() if role_title else None,
                is_org_admin,
                is_active,
                target_user_id,
                ctx.org_id,
            ),
        )
        row = await cur.fetchone()

    if row is None:
        return None

    return {
        "id": str(row[0]),
        "email": row[1],
        "full_name": row[2],
        "role_title": row[3],
        "department": row[4],
        "clearance_level": row[5],
        "is_org_admin": row[6],
        "is_active": row[7],
        "token_version": row[8],
        "created_at": row[9].isoformat(),
    }
