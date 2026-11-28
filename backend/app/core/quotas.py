"""Per-organization plan quotas, monthly usage metering, and sliding-window rate limits."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.db import RLSContext, get_db_pool, scoped_rls_transaction


class QuotaExceededError(Exception):
    """Raised when an organization exceeds its plan document or query allowance."""


class RateLimitExceededError(Exception):
    """Raised when an organization exceeds its per-minute API rate limit."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Rate limit exceeded. Retry in {retry_after_seconds}s.")
        self.retry_after_seconds = retry_after_seconds


_ORG_REQUEST_TIMESTAMPS: dict[UUID, deque[float]] = defaultdict(deque)


def reset_rate_limiter() -> None:
    """Clear in-memory rate limit buckets (for tests)."""
    _ORG_REQUEST_TIMESTAMPS.clear()


def enforce_org_rate_limit(org_id: UUID, *, limit_per_min: int | None = None) -> None:
    """Apply a sliding 60-second rate limit per organization."""
    limit = limit_per_min if limit_per_min is not None else settings.org_rate_limit_per_min
    if limit <= 0:
        return

    now = time.monotonic()
    cutoff = now - 60.0
    bucket = _ORG_REQUEST_TIMESTAMPS[org_id]
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()

    if len(bucket) >= limit:
        retry_after = max(1, int(60.0 - (now - bucket[0])) + 1)
        raise RateLimitExceededError(retry_after)

    bucket.append(now)


def _current_period_ym() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


async def enforce_document_quota(ctx: RLSContext) -> None:
    """Reject uploads when an organization reaches its plan max_documents limit."""
    pool = get_db_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT max_documents, org_document_count(id) FROM organizations WHERE id = %s",
            (ctx.org_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return
    max_docs, current_docs = int(row[0]), int(row[1])
    if current_docs >= max_docs:
        raise QuotaExceededError(
            f"Document quota ({max_docs}) reached for your organization plan."
        )


async def get_org_quota_snapshot(ctx: RLSContext) -> dict[str, Any]:
    """Return plan tier, document limits, and current month query usage."""
    period = _current_period_ym()
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT plan_tier, max_documents, monthly_query_limit, org_document_count(id) "
            "FROM organizations WHERE id = %s",
            (ctx.org_id,),
        )
        org_row = await cur.fetchone()
        plan_tier, max_docs, query_limit, total_docs = (
            org_row if org_row else ("free", 50, 500, 0)
        )

        await cur.execute(
            "SELECT query_count, tokens_used FROM usage_monthly WHERE period_ym = %s",
            (period,),
        )
        usage_row = await cur.fetchone()
        queries_used, tokens_used = usage_row if usage_row else (0, 0)

    return {
        "org_id": str(ctx.org_id),
        "plan_tier": plan_tier,
        "period_ym": period,
        "max_documents": int(max_docs),
        "documents_count": int(total_docs),
        "monthly_query_limit": int(query_limit),
        "queries_used": int(queries_used),
        "tokens_used": int(tokens_used),
    }


async def check_and_increment_query_usage(ctx: RLSContext) -> int:
    """Enforce monthly_query_limit and atomically increment usage_monthly."""
    period = _current_period_ym()
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT monthly_query_limit FROM organizations WHERE id = %s",
            (ctx.org_id,),
        )
        org_row = await cur.fetchone()
        limit = int(org_row[0]) if org_row else 500

        await cur.execute(
            "SELECT query_count FROM usage_monthly WHERE period_ym = %s FOR UPDATE",
            (period,),
        )
        usage_row = await cur.fetchone()
        current_count = int(usage_row[0]) if usage_row else 0

        if current_count >= limit:
            raise QuotaExceededError(
                f"Monthly query limit ({limit}) reached for your organization plan."
            )

        await cur.execute(
            """
            INSERT INTO usage_monthly (org_id, period_ym, query_count, tokens_used)
            VALUES (%s, %s, 1, 0)
            ON CONFLICT (org_id, period_ym)
            DO UPDATE SET query_count = usage_monthly.query_count + 1
            RETURNING query_count
            """,
            (ctx.org_id, period),
        )
        updated = await cur.fetchone()
        return int(updated[0]) if updated else current_count + 1
