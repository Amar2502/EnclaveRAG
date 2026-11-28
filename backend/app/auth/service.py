"""Database-backed auth, org registration, invitations, and instant session revocation."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

from app.core.config import settings
from app.core.db import RLSContext, get_db_pool, scoped_rls_transaction
from app.core.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)

DEFAULT_CLEARANCE_LABELS: dict[str, str] = {
    "1": "Company-Wide",
    "2": "Internal",
    "3": "Dept Confidential",
    "4": "Executive Only",
}


def _normalize_clearance_labels(raw: dict[str, Any] | None) -> dict[str, str]:
    merged = dict(DEFAULT_CLEARANCE_LABELS)
    if isinstance(raw, dict):
        for key in ("1", "2", "3", "4"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                merged[key] = val.strip()[:40]
    return merged


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


async def _send_invite_email(
    *,
    recipient_email: str,
    invite_url: str,
    role_title: str,
    department: str,
    clearance_level: int,
) -> bool:
    """Send invite email via Resend if RESEND_API_KEY is configured; non-fatal on failure."""
    if not settings.resend_api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.resend_from_email,
                    "to": [recipient_email],
                    "subject": "You're invited to EnclaveRAG",
                    "html": (
                        f"<p>You have been invited as <strong>{role_title}</strong> "
                        f"({department} · Tier L{clearance_level}).</p>"
                        f"<p><a href='{invite_url}'>Accept Invitation</a></p>"
                    ),
                },
            )
            resp.raise_for_status()
            return True
    except httpx.HTTPError as exc:
        logger.warning("Failed to send invite email via Resend: %s", exc)
        return False


def _build_auth_response(
    ctx: RLSContext,
    *,
    org_name: str,
    email: str,
    full_name: str,
    role_title: str,
    clearance_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
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
            "clearance_labels": _normalize_clearance_labels(clearance_labels),
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
                   u.is_org_admin, u.is_active, u.token_version, o.clearance_labels
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
        clearance_labels=row[12] if isinstance(row[12], dict) else None,
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
    invite_url = f"{base_url}/accept-invite?token={raw_token}"
    email_sent = await _send_invite_email(
        recipient_email=normalized_email,
        invite_url=invite_url,
        role_title=role_title.strip(),
        department=department.strip(),
        clearance_level=clearance_level,
    )
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
        "invite_url": invite_url,
        "email_sent": email_sent,
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
    labels = await get_org_clearance_labels(org_id)
    return _build_auth_response(
        ctx,
        org_name=str(org_name),
        email=str(email),
        full_name=full_name.strip(),
        role_title=str(role_title),
        clearance_labels=labels,
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


async def cancel_invitation(ctx: RLSContext, *, invite_id: UUID) -> bool:
    """Cancel a pending invitation strictly within the admin's org via RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            DELETE FROM invitations
            WHERE id = %s AND accepted_at IS NULL
            RETURNING id
            """,
            (invite_id,),
        )
        return (await cur.fetchone()) is not None


async def resend_invitation(
    ctx: RLSContext,
    *,
    invite_id: UUID,
    expires_days: int = 7,
) -> dict[str, Any] | None:
    """Regenerate token and extend expiry for a pending invitation under RLS."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_invite_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(days=expires_days)

    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE invitations
            SET token_hash = %s,
                expires_at = %s
            WHERE id = %s AND accepted_at IS NULL
            RETURNING id, email, role_title, department, clearance_level, expires_at, created_at
            """,
            (token_hash, expires_at, invite_id),
        )
        row = await cur.fetchone()

    if row is None:
        return None

    base_url = settings.app_base_url.rstrip("/")
    invite_url = f"{base_url}/accept-invite?token={raw_token}"
    email_sent = await _send_invite_email(
        recipient_email=str(row[1]),
        invite_url=invite_url,
        role_title=str(row[2]),
        department=str(row[3]),
        clearance_level=int(row[4]),
    )
    return {
        "id": str(row[0]),
        "org_id": str(ctx.org_id),
        "email": row[1],
        "role_title": row[2],
        "department": row[3],
        "clearance_level": row[4],
        "expires_at": row[5].isoformat(),
        "created_at": row[6].isoformat(),
        "invite_token": raw_token,
        "invite_url": invite_url,
        "email_sent": email_sent,
    }


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


async def get_org_clearance_labels(org_id: UUID) -> dict[str, str]:
    """Fetch customizable clearance tier labels for an organization."""
    pool = get_db_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT clearance_labels FROM organizations WHERE id = %s",
            (org_id,),
        )
        row = await cur.fetchone()
    raw = row[0] if row and isinstance(row[0], dict) else None
    return _normalize_clearance_labels(raw)


async def update_org_clearance_labels(
    ctx: RLSContext,
    labels: dict[str, str],
) -> dict[str, str]:
    """Update customizable clearance tier labels for the admin's organization."""
    normalized = _normalize_clearance_labels(labels)
    pool = get_db_pool()
    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE organizations
            SET clearance_labels = %s
            WHERE id = %s
            """,
            (Json(normalized), ctx.org_id),
        )
    return normalized


async def update_own_profile(
    ctx: RLSContext,
    *,
    full_name: str | None = None,
    current_password: str | None = None,
    new_password: str | None = None,
) -> dict[str, Any]:
    """Allow an authenticated user to update their display name or password."""
    pool = get_db_pool()
    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            "SELECT full_name, password_hash FROM users WHERE id = %s AND org_id = %s",
            (ctx.user_id, ctx.org_id),
        )
        row = await cur.fetchone()
        if row is None:
            raise AuthenticationError("User not found.")

        updated_name = full_name.strip() if full_name and full_name.strip() else str(row[0])
        new_hash: str | None = None
        if new_password:
            if not current_password or row[1] is None or not verify_password(current_password, row[1]):
                raise AuthenticationError("Current password is incorrect.")
            new_hash = hash_password(new_password)

        await cur.execute(
            """
            UPDATE users
            SET full_name = %s,
                password_hash = COALESCE(%s, password_hash)
            WHERE id = %s AND org_id = %s
            RETURNING email, full_name, role_title, department, clearance_level, is_org_admin
            """,
            (updated_name, new_hash, ctx.user_id, ctx.org_id),
        )
        updated = await cur.fetchone()
        assert updated is not None

    return {
        "email": updated[0],
        "full_name": updated[1],
        "role_title": updated[2],
        "department": updated[3],
        "clearance_level": updated[4],
        "is_org_admin": updated[5],
    }


async def _send_reset_email(*, recipient_email: str, reset_url: str) -> bool:
    if not settings.resend_api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.resend_from_email,
                    "to": [recipient_email],
                    "subject": "Reset your EnclaveRAG password",
                    "html": (
                        "<p>Use the one-time link below to reset your password (expires in 1 hour):</p>"
                        f"<p><a href='{reset_url}'>Reset Password</a></p>"
                    ),
                },
            )
            resp.raise_for_status()
            return True
    except httpx.HTTPError as exc:
        logger.warning("Failed to send password reset email via Resend: %s", exc)
        return False


async def request_password_reset(*, email: str) -> dict[str, Any]:
    """Create a one-time password reset token and email it if Resend is configured."""
    normalized_email = email.strip().lower()
    pool = get_db_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT id, org_id, is_active FROM users WHERE lower(email) = %s",
            (normalized_email,),
        )
        row = await cur.fetchone()

    if row is None or not row[2]:
        return {"status": "ok", "email_sent": False}

    user_id, org_id, _ = row
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_invite_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    target_ctx = RLSContext(
        org_id=org_id,
        user_id=user_id,
        clearance_level=1,
        department="General",
    )
    async with scoped_rls_transaction(target_ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO password_resets (org_id, user_id, token_hash, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (org_id, user_id, token_hash, expires_at),
        )

    reset_url = f"{settings.app_base_url.rstrip('/')}/reset-password?token={raw_token}"
    email_sent = await _send_reset_email(recipient_email=normalized_email, reset_url=reset_url)
    return {"status": "ok", "email_sent": email_sent}


async def confirm_password_reset(*, raw_token: str, new_password: str) -> None:
    """Validate a one-time reset token, update password_hash, and revoke old sessions."""
    token_hash = _hash_invite_token(raw_token.strip())
    pw_hash = hash_password(new_password)
    pool = get_db_pool()

    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute("SELECT * FROM app.consume_password_reset(%s)", (token_hash,))
        row = await cur.fetchone()
        if row is None:
            raise InvalidInvitationError("Invalid or expired password reset token.")

        reset_id, org_id, user_id, expires_at, used_at = row
        if used_at is not None or expires_at <= datetime.now(UTC):
            raise InvalidInvitationError("Invalid or expired password reset token.")

        await cur.execute(
            """
            UPDATE users
            SET password_hash = %s,
                token_version = token_version + 1
            WHERE id = %s AND org_id = %s
            """,
            (pw_hash, user_id, org_id),
        )
        await cur.execute(
            "SELECT set_config('app.current_org_id', %s, true)",
            (str(org_id),),
        )
        await cur.execute(
            "UPDATE password_resets SET used_at = NOW() WHERE id = %s",
            (reset_id,),
        )
