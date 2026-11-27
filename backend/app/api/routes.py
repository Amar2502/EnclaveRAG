"""Phase 1 API routes verifying JWT -> SET LOCAL RLS round-trip."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.db import RLSContext, scoped_rls_transaction
from app.core.security import get_current_rls_context

router = APIRouter()


@router.get("/whoami", tags=["auth"])
async def whoami(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Echo verified JWT claims alongside active PostgreSQL SET LOCAL session settings."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT current_setting('app.org_id', true), "
            "current_setting('app.clearance_level', true), "
            "current_setting('app.user_id', true)"
        )
        row = await cur.fetchone()

    db_org_id, db_clearance, db_user_id = row if row else (None, None, None)
    return {
        "jwt_claims": {
            "user_id": str(ctx.user_id),
            "org_id": str(ctx.org_id),
            "clearance_level": ctx.clearance_level,
            "department": ctx.department,
        },
        "postgres_session": {
            "app.org_id": db_org_id,
            "app.clearance_level": int(db_clearance) if db_clearance else None,
            "app.user_id": db_user_id,
        },
    }
