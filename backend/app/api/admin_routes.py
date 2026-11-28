"""Organization Admin governance routes (users, clearances, invites, session revocation)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.service import (
    ConflictError,
    create_invitation,
    list_org_invitations,
    list_org_users,
    revoke_user_sessions,
    update_org_user,
)
from app.core.db import RLSContext
from app.core.security import require_org_admin

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateInviteRequest(BaseModel):
    """Payload to invite an employee into the admin's organization."""

    email: str = Field(min_length=5, max_length=255)
    role_title: str = Field(min_length=1, max_length=100)
    department: str = Field(default="Engineering", min_length=1, max_length=100)
    clearance_level: int = Field(ge=1, le=4)


class UpdateUserRequest(BaseModel):
    """Payload for updating employee clearance, department, or active status."""

    clearance_level: int | None = Field(default=None, ge=1, le=4)
    department: str | None = Field(default=None, min_length=1, max_length=100)
    role_title: str | None = Field(default=None, min_length=1, max_length=100)
    is_org_admin: bool | None = None
    is_active: bool | None = None


@router.get("/users")
async def get_users(
    ctx: Annotated[RLSContext, Depends(require_org_admin)],
) -> dict[str, list[dict[str, object]]]:
    """List employees in the admin's organization."""
    users = await list_org_users(ctx)
    return {"users": users}


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: UUID,
    payload: UpdateUserRequest,
    ctx: Annotated[RLSContext, Depends(require_org_admin)],
) -> dict[str, object]:
    """Update an employee's clearance/status and immediately revoke prior tokens."""
    try:
        updated = await update_org_user(
            ctx,
            target_user_id=user_id,
            clearance_level=payload.clearance_level,
            department=payload.department,
            role_title=payload.role_title,
            is_org_admin=payload.is_org_admin,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return {"user": updated}


@router.post("/users/{user_id}/revoke")
async def revoke_sessions(
    user_id: UUID,
    ctx: Annotated[RLSContext, Depends(require_org_admin)],
) -> dict[str, str]:
    """Immediately revoke all active JWTs for an employee in this organization."""
    revoked = await revoke_user_sessions(org_id=ctx.org_id, user_id=user_id)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return {"status": "revoked"}


@router.get("/invites")
async def get_invites(
    ctx: Annotated[RLSContext, Depends(require_org_admin)],
) -> dict[str, list[dict[str, object]]]:
    """List invitations scoped to the admin's organization via RLS."""
    invites = await list_org_invitations(ctx)
    return {"invites": invites}


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def post_invite(
    payload: CreateInviteRequest,
    ctx: Annotated[RLSContext, Depends(require_org_admin)],
) -> dict[str, object]:
    """Issue a one-time invitation token for a new employee."""
    try:
        invite = await create_invitation(
            ctx,
            email=payload.email,
            role_title=payload.role_title,
            department=payload.department,
            clearance_level=payload.clearance_level,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"invite": invite}
