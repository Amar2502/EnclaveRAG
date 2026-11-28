"""SaaS authentication endpoints (org registration, login, logout, invite acceptance)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.service import (
    AuthenticationError,
    ConflictError,
    InvalidInvitationError,
    accept_invitation,
    authenticate_user,
    confirm_password_reset,
    register_organization,
    request_password_reset,
    revoke_user_sessions,
    update_own_profile,
)
from app.core.db import RLSContext
from app.core.security import get_current_rls_context

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterOrgRequest(BaseModel):
    """Payload to provision a new tenant organization and initial Org Admin."""

    org_name: str = Field(min_length=2, max_length=120)
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    department: str = Field(default="Executive", min_length=1, max_length=100)


class LoginRequest(BaseModel):
    """Payload for email/password login."""

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class AcceptInviteRequest(BaseModel):
    """Payload to accept an org invitation and create employee credentials."""

    token: str = Field(min_length=10)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)


@router.post("/register-org", status_code=status.HTTP_201_CREATED)
async def register_org(payload: RegisterOrgRequest) -> dict[str, object]:
    """Create a new organization and its first L4 Org Admin user."""
    try:
        return await register_organization(
            org_name=payload.org_name,
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password,
            department=payload.department,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/login")
async def login(payload: LoginRequest) -> dict[str, object]:
    """Verify credentials and issue a signed JWT."""
    try:
        return await authenticate_user(email=payload.email, password=payload.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/logout")
async def logout(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, str]:
    """Revoke all active JWTs for the current user via token_version increment."""
    await revoke_user_sessions(org_id=ctx.org_id, user_id=ctx.user_id)
    return {"status": "logged_out"}


@router.post("/accept-invite", status_code=status.HTTP_201_CREATED)
async def accept_invite(payload: AcceptInviteRequest) -> dict[str, object]:
    """Accept an organization invite token and issue an employee JWT."""
    try:
        return await accept_invitation(
            raw_token=payload.token,
            full_name=payload.full_name,
            password=payload.password,
        )
    except InvalidInvitationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


class UpdateProfileRequest(BaseModel):
    """Payload for updating the signed-in user's name or password."""

    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    current_password: str | None = Field(default=None, min_length=1, max_length=128)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    """Payload to request a one-time password reset email."""

    email: str = Field(min_length=5, max_length=255)


class ResetPasswordRequest(BaseModel):
    """Payload to complete a password reset using a one-time token."""

    token: str = Field(min_length=10)
    new_password: str = Field(min_length=8, max_length=128)


@router.patch("/me")
async def update_me(
    payload: UpdateProfileRequest,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Allow the signed-in user to update their display name or password."""
    try:
        user = await update_own_profile(
            ctx,
            full_name=payload.full_name,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"user": user}


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest) -> dict[str, object]:
    """Request a one-time password reset link (non-enumerating)."""
    return await request_password_reset(email=payload.email)


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest) -> dict[str, str]:
    """Reset a user's password with a valid one-time token."""
    try:
        await confirm_password_reset(raw_token=payload.token, new_password=payload.new_password)
    except InvalidInvitationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"status": "password_reset"}
