"""Phase 2 integration tests: personas, ingestion, file upload, and O(1) reclassification."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.db import RLSContext, close_db_pool, init_db_pool, scoped_rls_transaction
from app.main import app
from tests.conftest import IsolatedTestWorld, make_unit_vector


async def _get_token(client: AsyncClient, email: str) -> str:
    res = await client.post("/api/v1/auth/persona-token", json={"email": email})
    assert res.status_code == 200
    return str(res.json()["access_token"])


async def test_personas_and_document_listing_isolation(isolated_world: IsolatedTestWorld) -> None:
    """Persona listing works and GET /documents respects tenant + clearance boundaries."""
    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            personas_res = await client.get("/api/v1/personas")
            assert personas_res.status_code == 200
            emails = {p["email"] for p in personas_res.json()["personas"]}
            assert isolated_world.email_a_l1 in emails

            missing_res = await client.post(
                "/api/v1/auth/persona-token",
                json={"email": "unknown@nonexistent.local"},
            )
            assert missing_res.status_code == 404

            tok_l1 = await _get_token(client, isolated_world.email_a_l1)
            tok_l4 = await _get_token(client, isolated_world.email_a_l4)
            tok_b4 = await _get_token(client, isolated_world.email_b_l4)

            docs_l1 = await client.get(
                "/api/v1/documents", headers={"Authorization": f"Bearer {tok_l1}"}
            )
            docs_l4 = await client.get(
                "/api/v1/documents", headers={"Authorization": f"Bearer {tok_l4}"}
            )
            docs_b4 = await client.get(
                "/api/v1/documents", headers={"Authorization": f"Bearer {tok_b4}"}
            )
    finally:
        await close_db_pool()

    assert [d["title"] for d in docs_l1.json()["documents"]] == ["Org A Handbook"]
    assert {d["title"] for d in docs_l4.json()["documents"]} == {
        "Org A Handbook",
        "Org A Engineering Roadmap",
        "Org A Vendor NDA",
        "Org A Project Helios",
    }
    assert {d["title"] for d in docs_b4.json()["documents"]} == {
        "Org B Public FAQ",
        "Org B Project Helios",
    }


async def test_ingest_text_upload_and_privilege_block(
    isolated_world: IsolatedTestWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2 user can ingest L2 text/files, but is blocked (403) from writing L4 docs."""

    async def fake_embed_documents(texts: list[str]) -> list[list[float]]:
        return [make_unit_vector(100 + i, settings.embedding_dimension) for i in range(len(texts))]

    monkeypatch.setattr("app.ingestion.service.embed_documents", fake_embed_documents)

    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            tok_l2 = await _get_token(client, isolated_world.email_a_l2)
            headers = {"Authorization": f"Bearer {tok_l2}"}

            blocked = await client.post(
                "/api/v1/documents",
                headers=headers,
                json={
                    "title": "Blocked L4",
                    "department": "Executive",
                    "clearance_level": 4,
                    "content": "Should be rejected.",
                },
            )
            assert blocked.status_code == 403

            created = await client.post(
                "/api/v1/documents",
                headers=headers,
                json={
                    "title": "Sprint 15 Notes",
                    "department": "Engineering",
                    "clearance_level": 2,
                    "content": "Firmware test coverage reached 92%.",
                },
            )
            assert created.status_code == 201
            assert created.json()["document"]["chunk_count"] == 1

            uploaded = await client.post(
                "/api/v1/documents/upload",
                headers=headers,
                data={"clearance_level": "2", "department": "Engineering"},
                files={"file": ("notes.md", b"# Firmware\n\nDMA latency reduced.", "text/markdown")},
            )
            assert uploaded.status_code == 201
            assert uploaded.json()["document"]["title"] == "notes.md"
    finally:
        await close_db_pool()


async def test_o1_reclassification_and_zero_existence_leakage(
    isolated_world: IsolatedTestWorld,
) -> None:
    """Reclassifying L2 -> L4 hides chunks immediately without altering chunk IDs."""
    await init_db_pool()
    try:
        # Capture existing chunk ID before reclassification
        ctx_a4 = RLSContext(
            org_id=isolated_world.org_a,
            user_id=isolated_world.user_a_l4,
            clearance_level=4,
            department="Executive",
            is_org_admin=True,
        )
        async with scoped_rls_transaction(ctx_a4) as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM document_chunks WHERE document_id = %s",
                (isolated_world.doc_a_l2,),
            )
            before_chunk_ids = [row[0] for row in await cur.fetchall()]

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            tok_l2 = await _get_token(client, isolated_world.email_a_l2)
            tok_l4 = await _get_token(client, isolated_world.email_a_l4)

            # L4 upgrades L2 doc -> L4
            upgrade_res = await client.patch(
                f"/api/v1/documents/{isolated_world.doc_a_l2}/classification",
                headers={"Authorization": f"Bearer {tok_l4}"},
                json={"clearance_level": 4},
            )
            assert upgrade_res.status_code == 200
            assert upgrade_res.json()["document"]["classification_tag"] == "L4_EXECUTIVE"

            # L2 immediately stops seeing the document
            docs_l2 = await client.get(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {tok_l2}"},
            )
            assert [d["id"] for d in docs_l2.json()["documents"]] == [str(isolated_world.doc_a_l1)]

            # L2 attempting to downgrade an L4 doc receives 404 (zero existence leakage)
            downgrade_attempt = await client.patch(
                f"/api/v1/documents/{isolated_world.doc_a_l2}/classification",
                headers={"Authorization": f"Bearer {tok_l2}"},
                json={"clearance_level": 1},
            )
            assert downgrade_attempt.status_code == 404

            # L2 attempting to promote an L1 doc to L4 receives 403
            promote_attempt = await client.patch(
                f"/api/v1/documents/{isolated_world.doc_a_l1}/classification",
                headers={"Authorization": f"Bearer {tok_l2}"},
                json={"clearance_level": 4},
            )
            assert promote_attempt.status_code == 403

        # Verify chunk row IDs were untouched (O(1) document metadata update only)
        async with scoped_rls_transaction(ctx_a4) as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM document_chunks WHERE document_id = %s",
                (isolated_world.doc_a_l2,),
            )
            after_chunk_ids = [row[0] for row in await cur.fetchall()]
        assert after_chunk_ids == before_chunk_ids
    finally:
        await close_db_pool()
