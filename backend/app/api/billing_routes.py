"""Organization usage metering and Stripe webhook billing routes."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.core.config import settings
from app.core.db import RLSContext, get_db_pool
from app.core.quotas import get_org_quota_snapshot
from app.core.security import get_current_rls_context

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_LIMITS: dict[str, tuple[int, int]] = {
    "free": (50, 500),
    "pro": (1000, 25000),
    "enterprise": (50000, 500000),
}


def _verify_stripe_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Validate Stripe-Signature `t=...,v1=...` HMAC-SHA256 header."""
    parts = dict(item.split("=", 1) for item in signature_header.split(",") if "=" in item)
    timestamp = parts.get("t")
    v1_sig = parts.get("v1")
    if not timestamp or not v1_sig:
        return False

    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1_sig)


@router.get("/usage")
async def billing_usage(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Return current plan tier and monthly document/query usage for caller's org."""
    return {"usage": await get_org_quota_snapshot(ctx)}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> dict[str, object]:
    """Handle Stripe plan upgrade/downgrade events and update org quotas."""
    raw_body = await request.body()
    if settings.stripe_webhook_secret and (
        not stripe_signature
        or not _verify_stripe_signature(
            raw_body, stripe_signature, settings.stripe_webhook_secret
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe webhook signature.",
        )

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON webhook payload.",
        ) from exc

    event_type = str(event.get("type", ""))
    if event_type not in {
        "checkout.session.completed",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        return {"status": "ignored", "type": event_type}

    data_obj = event.get("data", {}).get("object", {})
    metadata = data_obj.get("metadata", {})
    raw_org_id = metadata.get("org_id")
    plan_tier = (
        "free"
        if event_type == "customer.subscription.deleted"
        else str(metadata.get("plan_tier", "pro")).lower()
    )

    if not raw_org_id or plan_tier not in PLAN_LIMITS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook missing valid metadata.org_id or plan_tier.",
        )

    org_id = UUID(str(raw_org_id))
    max_docs, monthly_limit = PLAN_LIMITS[plan_tier]

    pool = get_db_pool()
    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE organizations
            SET plan_tier = %s,
                max_documents = %s,
                monthly_query_limit = %s
            WHERE id = %s
            RETURNING id
            """,
            (plan_tier, max_docs, monthly_limit, org_id),
        )
        updated = await cur.fetchone()

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    return {
        "status": "updated",
        "org_id": str(org_id),
        "plan_tier": plan_tier,
        "max_documents": max_docs,
        "monthly_query_limit": monthly_limit,
    }
