"""Phase UX-4 integration tests: audit user names, org tier labels, profile & password reset."""

from __future__ import annotations

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.db import close_db_pool, init_db_pool
from app.core.quotas import reset_rate_limiter
from app.main import app
from app.retrieval.hybrid_search import RetrievedChunk
from tests.conftest import IsolatedTestWorld, make_unit_vector


async def _get_token(client: AsyncClient, email: str) -> str:
    res = await client.post("/api/v1/auth/persona-token", json={"email": email})
    assert res.status_code == 200
    return str(res.json()["access_token"])


async def test_audit_user_identity_and_custom_org_tier_labels(
    isolated_world: IsolatedTestWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit logs include user_name/user_email; admins can customize org clearance_labels."""
    dim = settings.embedding_dimension
    reset_rate_limiter()

    async def fake_embed_query(text: str) -> list[float]:
        return make_unit_vector(410, dim)

    async def fake_synthesize(
        query: str,
        chunks: list[RetrievedChunk],
        history: list[dict[str, str]] | None = None,
    ) -> str:
        return "Grounded answer."

    monkeypatch.setattr("app.api.routes.embed_query", fake_embed_query)
    monkeypatch.setattr("app.api.routes.synthesize_answer", fake_synthesize)

    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            tok_a4 = await _get_token(client, isolated_world.email_a_l4)

            # Customize org clearance labels
            patch_res = await client.patch(
                "/api/v1/admin/org-settings",
                headers={"Authorization": f"Bearer {tok_a4}"},
                json={
                    "clearance_labels": {
                        "1": "Everyone",
                        "2": "Staff Only",
                        "3": "Team Secret",
                        "4": "Boardroom",
                    }
                },
            )
            assert patch_res.status_code == 200
            assert patch_res.json()["clearance_labels"]["4"] == "Boardroom"

            get_res = await client.get(
                "/api/v1/admin/org-settings",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert get_res.status_code == 200
            assert get_res.json()["clearance_labels"]["1"] == "Everyone"

            # Run a query and verify audit log includes user_name & user_email
            q_res = await client.post(
                "/api/v1/query",
                headers={"Authorization": f"Bearer {tok_a4}"},
                json={"query": "Test audit identity", "top_k": 3},
            )
            assert q_res.status_code == 200

            audit_res = await client.get(
                "/api/v1/audit",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert audit_res.status_code == 200
            logs = audit_res.json()["audit_logs"]
            assert logs
            assert logs[0]["user_email"] == isolated_world.email_a_l4
            assert logs[0]["user_name"] is not None
    finally:
        await close_db_pool()


async def test_profile_update_and_password_reset_flow(
    isolated_world: IsolatedTestWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Users can update name/password via /auth/me and reset forgotten passwords via token."""
    captured_reset_url: dict[str, str] = {}

    async def fake_send_reset_email(*, recipient_email: str, reset_url: str) -> bool:
        captured_reset_url["url"] = reset_url
        return True

    monkeypatch.setattr("app.auth.service._send_reset_email", fake_send_reset_email)

    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            reg_res = await client.post(
                "/api/v1/auth/register-org",
                json={
                    "org_name": "UX4 Test Org",
                    "full_name": "Initial Name",
                    "email": "ux4_owner@example.com",
                    "password": "OldPassword123!",
                    "department": "Executive",
                },
            )
            assert reg_res.status_code == 201
            token = reg_res.json()["access_token"]
            assert "clearance_labels" in reg_res.json()["user"]

            # Update display name and password
            me_res = await client.patch(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "full_name": "Updated Owner",
                    "current_password": "OldPassword123!",
                    "new_password": "NewPassword456!",
                },
            )
            assert me_res.status_code == 200
            assert me_res.json()["user"]["full_name"] == "Updated Owner"

            # Old password fails, new password succeeds
            bad_login = await client.post(
                "/api/v1/auth/login",
                json={"email": "ux4_owner@example.com", "password": "OldPassword123!"},
            )
            assert bad_login.status_code == 401

            good_login = await client.post(
                "/api/v1/auth/login",
                json={"email": "ux4_owner@example.com", "password": "NewPassword456!"},
            )
            assert good_login.status_code == 200

            # Request password reset and consume token
            forgot_res = await client.post(
                "/api/v1/auth/forgot-password",
                json={"email": "ux4_owner@example.com"},
            )
            assert forgot_res.status_code == 200
            assert forgot_res.json()["email_sent"] is True
            raw_token = captured_reset_url["url"].split("token=")[1]

            reset_res = await client.post(
                "/api/v1/auth/reset-password",
                json={"token": raw_token, "new_password": "ResetPassword789!"},
            )
            assert reset_res.status_code == 200

            final_login = await client.post(
                "/api/v1/auth/login",
                json={"email": "ux4_owner@example.com", "password": "ResetPassword789!"},
            )
            assert final_login.status_code == 200
    finally:
        await close_db_pool()
        async with await psycopg.AsyncConnection.connect(
            settings.admin_database_url,
            autocommit=True,
        ) as conn:
            await conn.execute("DELETE FROM organizations WHERE name = 'UX4 Test Org'")
