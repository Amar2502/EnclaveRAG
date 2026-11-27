"""Phase 1 unit tests: RLSContext bounds, JWT round-trip, and auth route guards."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.db import RLSContext
from app.core.security import create_access_token, verify_access_token
from app.main import app


def test_rls_context_enforces_clearance_bounds() -> None:
    """Clearance level must stay strictly within 1..4."""
    with pytest.raises(ValueError, match="clearance_level"):
        RLSContext(org_id=uuid4(), user_id=uuid4(), clearance_level=0)

    with pytest.raises(ValueError, match="clearance_level"):
        RLSContext(org_id=uuid4(), user_id=uuid4(), clearance_level=5)

    ctx = RLSContext(org_id=uuid4(), user_id=uuid4(), clearance_level=4)
    assert ctx.clearance_level == 4


def test_jwt_round_trip_preserves_claims() -> None:
    """Signed JWT decodes back to the exact RLSContext claims."""
    ctx = RLSContext(
        org_id=uuid4(),
        user_id=uuid4(),
        clearance_level=3,
        department="Security",
    )
    token = create_access_token(ctx)
    assert verify_access_token(token) == ctx


def test_invalid_jwt_raises_401() -> None:
    """Malformed or tampered tokens must fail with HTTP 401."""
    with pytest.raises(HTTPException) as exc_info:
        verify_access_token("invalid.jwt.token")
    assert exc_info.value.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/whoami"),
        ("GET", "/api/v1/documents"),
        ("GET", "/api/v1/audit"),
        ("POST", "/api/v1/query"),
    ],
)
async def test_protected_routes_require_bearer_token(method: str, path: str) -> None:
    """All tenant-scoped endpoints reject unauthenticated requests with 401."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.request(method, path)

    assert response.status_code == 401
