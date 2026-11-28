"""Phase S1 integration tests: SaaS org signup, invites, admin RBAC, and instant revocation."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.db import close_db_pool, init_db_pool
from app.main import app


async def test_org_registration_invite_and_instant_revocation() -> None:
    """Verify org onboarding, employee invite flow, admin RBAC, and token_version revocation."""
    suffix = uuid4().hex[:8]
    org_name = f"SaaS Corp {suffix}"
    admin_email = f"admin-{suffix}@saas.local"
    emp_email = f"emp-{suffix}@saas.local"
    created_org_id: UUID | None = None

    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            # 1. Register new tenant organization -> L4 Org Admin
            reg_res = await client.post(
                "/api/v1/auth/register-org",
                json={
                    "org_name": org_name,
                    "full_name": "Dana Founder",
                    "email": admin_email,
                    "password": "StrongPassword123!",
                    "department": "Executive",
                },
            )
            assert reg_res.status_code == 201
            reg_body = reg_res.json()
            created_org_id = UUID(reg_body["user"]["org_id"])
            admin_token = reg_body["access_token"]
            assert reg_body["user"]["is_org_admin"] is True
            assert reg_body["user"]["clearance_level"] == 4

            # Duplicate email/org rejected with 409
            dup_res = await client.post(
                "/api/v1/auth/register-org",
                json={
                    "org_name": org_name,
                    "full_name": "Dana Founder",
                    "email": admin_email,
                    "password": "StrongPassword123!",
                },
            )
            assert dup_res.status_code == 409

            # 2. Login check (bad password -> 401, good password -> 200)
            bad_login = await client.post(
                "/api/v1/auth/login",
                json={"email": admin_email, "password": "WrongPassword!"},
            )
            assert bad_login.status_code == 401

            good_login = await client.post(
                "/api/v1/auth/login",
                json={"email": admin_email, "password": "StrongPassword123!"},
            )
            assert good_login.status_code == 200

            # 3. Admin invites an L2 Engineering employee
            inv_res = await client.post(
                "/api/v1/admin/invites",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "email": emp_email,
                    "role_title": "Backend Engineer",
                    "department": "Engineering",
                    "clearance_level": 2,
                },
            )
            assert inv_res.status_code == 201
            invite_token = inv_res.json()["invite"]["invite_token"]

            # 4. Invitee accepts invitation -> receives L2 non-admin JWT
            accept_res = await client.post(
                "/api/v1/auth/accept-invite",
                json={
                    "token": invite_token,
                    "full_name": "Sam Engineer",
                    "password": "EmpPassword123!",
                },
            )
            assert accept_res.status_code == 201
            emp_body = accept_res.json()
            emp_id = emp_body["user"]["user_id"]
            emp_token = emp_body["access_token"]
            assert emp_body["user"]["clearance_level"] == 2
            assert emp_body["user"]["is_org_admin"] is False

            # Reusing same invite token fails
            reuse_res = await client.post(
                "/api/v1/auth/accept-invite",
                json={
                    "token": invite_token,
                    "full_name": "Sam Clone",
                    "password": "EmpPassword123!",
                },
            )
            assert reuse_res.status_code == 400

            # Non-admin blocked from /admin/users (403)
            non_admin = await client.get(
                "/api/v1/admin/users",
                headers={"Authorization": f"Bearer {emp_token}"},
            )
            assert non_admin.status_code == 403

            # 5. Admin demotes employee L2 -> L1; old L2 token is revoked immediately (401)
            patch_res = await client.patch(
                f"/api/v1/admin/users/{emp_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"clearance_level": 1},
            )
            assert patch_res.status_code == 200
            assert patch_res.json()["user"]["clearance_level"] == 1

            stale_whoami = await client.get(
                "/api/v1/whoami",
                headers={"Authorization": f"Bearer {emp_token}"},
            )
            assert stale_whoami.status_code == 401

            # Employee logs back in -> gets fresh L1 JWT
            emp_relogin = await client.post(
                "/api/v1/auth/login",
                json={"email": emp_email, "password": "EmpPassword123!"},
            )
            assert emp_relogin.status_code == 200
            fresh_emp_token = emp_relogin.json()["access_token"]
            assert emp_relogin.json()["user"]["clearance_level"] == 1

            # 6. Logout revokes active JWT immediately
            logout_res = await client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {fresh_emp_token}"},
            )
            assert logout_res.status_code == 200

            post_logout = await client.get(
                "/api/v1/whoami",
                headers={"Authorization": f"Bearer {fresh_emp_token}"},
            )
            assert post_logout.status_code == 401
    finally:
        await close_db_pool()
        if created_org_id is not None:
            async with await psycopg.AsyncConnection.connect(
                settings.admin_database_url,
                autocommit=True,
            ) as admin_conn:
                await admin_conn.execute(
                    "DELETE FROM organizations WHERE id = %s",
                    (created_org_id,),
                )


async def test_demo_routes_disabled_in_production_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ENABLE_DEMO_MODE=false, demo persona endpoints return 404."""
    monkeypatch.setattr(settings, "enable_demo_mode", False)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        personas_res = await client.get("/api/v1/personas")
        token_res = await client.post(
            "/api/v1/auth/persona-token",
            json={"email": "intern@apex.example.com"},
        )

    assert personas_res.status_code == 404
    assert token_res.status_code == 404
