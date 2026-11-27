"""Phase 1 integration tests: PostgreSQL role privileges, RLS isolation, and /whoami."""

from __future__ import annotations

import psycopg
from httpx import ASGITransport, AsyncClient
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings
from app.core.db import (
    RLSContext,
    close_db_pool,
    init_db_pool,
    scoped_rls_transaction,
)
from app.core.security import create_access_token
from app.main import app
from tests.conftest import IsolatedTestWorld


async def test_runtime_role_cannot_bypass_rls() -> None:
    """Confirm runtime role is enclave_app with NOSUPERUSER and NOBYPASSRLS."""
    async with (
        await psycopg.AsyncConnection.connect(settings.database_url) as conn,
        conn.cursor() as cur,
    ):
        await cur.execute(
            "SELECT current_user, rolsuper, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )
        row = await cur.fetchone()

    assert row is not None
    role_name, is_super, bypass_rls = row
    assert role_name == "enclave_app"
    assert is_super is False
    assert bypass_rls is False


async def test_unscoped_query_returns_zero_rows(isolated_world: IsolatedTestWorld) -> None:
    """Without SET LOCAL session claims, unconstrained SELECT returns 0 rows."""
    _ = isolated_world
    async with (
        await psycopg.AsyncConnection.connect(settings.database_url) as conn,
        conn.cursor() as cur,
    ):
        await cur.execute("SELECT count(*) FROM documents")
        doc_count = (await cur.fetchone())[0]
        await cur.execute("SELECT count(*) FROM document_chunks")
        chunk_count = (await cur.fetchone())[0]

    assert doc_count == 0
    assert chunk_count == 0


async def test_hierarchical_clearance_and_pool_reset(isolated_world: IsolatedTestWorld) -> None:
    """Verify L1..L4 no-read-up, cross-org isolation, and single-connection pool reset."""
    pool = AsyncConnectionPool(conninfo=settings.database_url, min_size=1, max_size=1, open=False)
    await pool.open(wait=True)
    try:
        async with scoped_rls_transaction(
            RLSContext(
                org_id=isolated_world.org_a,
                user_id=isolated_world.user_a_l1,
                clearance_level=1,
            ),
            pool=pool,
        ) as conn:
            cur = await conn.execute(
                "SELECT d.title FROM document_chunks c "
                "JOIN documents d ON d.id = c.document_id ORDER BY d.clearance_level"
            )
            assert [r[0] for r in await cur.fetchall()] == ["Org A Handbook"]

        async with scoped_rls_transaction(
            RLSContext(
                org_id=isolated_world.org_a,
                user_id=isolated_world.user_a_l2,
                clearance_level=2,
            ),
            pool=pool,
        ) as conn:
            cur = await conn.execute(
                "SELECT d.title FROM document_chunks c "
                "JOIN documents d ON d.id = c.document_id ORDER BY d.clearance_level"
            )
            assert [r[0] for r in await cur.fetchall()] == [
                "Org A Handbook",
                "Org A Engineering Roadmap",
            ]

        async with scoped_rls_transaction(
            RLSContext(
                org_id=isolated_world.org_a,
                user_id=isolated_world.user_a_l4,
                clearance_level=4,
            ),
            pool=pool,
        ) as conn:
            cur = await conn.execute(
                "SELECT d.title FROM document_chunks c "
                "JOIN documents d ON d.id = c.document_id ORDER BY d.clearance_level"
            )
            assert [r[0] for r in await cur.fetchall()] == [
                "Org A Handbook",
                "Org A Engineering Roadmap",
                "Org A Vendor NDA",
                "Org A Project Helios",
            ]

        # Same pooled connection reused by Org B L1 must see only Org B L1
        async with scoped_rls_transaction(
            RLSContext(
                org_id=isolated_world.org_b,
                user_id=isolated_world.user_b_l1,
                clearance_level=1,
            ),
            pool=pool,
        ) as conn:
            cur = await conn.execute(
                "SELECT d.title FROM document_chunks c "
                "JOIN documents d ON d.id = c.document_id ORDER BY d.clearance_level"
            )
            assert [r[0] for r in await cur.fetchall()] == ["Org B Public FAQ"]

        # Unscoped check after transaction commits must see 0 rows
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT count(*) FROM document_chunks")
            assert (await cur.fetchone())[0] == 0
    finally:
        await pool.close()


async def test_whoami_round_trip(isolated_world: IsolatedTestWorld) -> None:
    """Verify FastAPI /whoami binds JWT claims into PostgreSQL SET LOCAL settings."""
    ctx = RLSContext(
        org_id=isolated_world.org_a,
        user_id=isolated_world.user_a_l2,
        clearance_level=2,
        department="Engineering",
    )
    token = create_access_token(ctx)

    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/api/v1/whoami",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        await close_db_pool()

    assert response.status_code == 200
    body = response.json()
    assert body["jwt_claims"]["org_id"] == str(ctx.org_id)
    assert body["postgres_session"]["app.org_id"] == str(ctx.org_id)
    assert body["postgres_session"]["app.clearance_level"] == 2
