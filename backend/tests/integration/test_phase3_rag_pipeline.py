"""Phase 3 integration tests: hybrid RRF search, /query, citation proxy, and audit logs."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.db import RLSContext, close_db_pool, init_db_pool
from app.llm.synthesizer import NO_ACCESSIBLE_INFO_MESSAGE
from app.main import app
from app.retrieval.hybrid_search import RetrievedChunk, hybrid_rrf_search
from tests.conftest import IsolatedTestWorld, make_unit_vector


async def _get_token(client: AsyncClient, email: str) -> str:
    res = await client.post("/api/v1/auth/persona-token", json={"email": email})
    assert res.status_code == 200
    return str(res.json()["access_token"])


async def test_hybrid_rrf_search_enforces_tenant_and_clearance(
    isolated_world: IsolatedTestWorld,
) -> None:
    """Hybrid search retrieves only authorized chunks matching org_id and clearance."""
    dim = settings.embedding_dimension
    await init_db_pool()
    try:
        # L1 queries for L3 NDA discount using L3's vector -> filtered by RLS + min_vector_score
        res_l1 = await hybrid_rrf_search(
            RLSContext(
                org_id=isolated_world.org_a,
                user_id=isolated_world.user_a_l1,
                clearance_level=1,
            ),
            query="PrecisionDrive harmonic actuator discount",
            query_embedding=make_unit_vector(20, dim),
            top_k=5,
        )
        assert res_l1.chunks == []

        # L4 Org A queries Project Helios -> gets Org A Helios only
        res_a4 = await hybrid_rrf_search(
            RLSContext(
                org_id=isolated_world.org_a,
                user_id=isolated_world.user_a_l4,
                clearance_level=4,
            ),
            query="Project Helios",
            query_embedding=make_unit_vector(30, dim),
            top_k=5,
        )
        assert [c.document_title for c in res_a4.chunks] == ["Org A Project Helios"]

        # L4 Org B queries Project Helios -> gets Org B Helios only
        res_b4 = await hybrid_rrf_search(
            RLSContext(
                org_id=isolated_world.org_b,
                user_id=isolated_world.user_b_l4,
                clearance_level=4,
            ),
            query="Project Helios",
            query_embedding=make_unit_vector(50, dim),
            top_k=5,
        )
        assert [c.document_title for c in res_b4.chunks] == ["Org B Project Helios"]
    finally:
        await close_db_pool()


async def test_query_citation_proxy_and_audit_isolation(
    isolated_world: IsolatedTestWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end /query, /documents/{id}/view proxy, and tenant-isolated /audit."""
    dim = settings.embedding_dimension

    async def fake_embed_query(query: str) -> list[float]:
        if "PTO" in query or "remote" in query:
            return make_unit_vector(0, dim)
        if "Helios" in query:
            return make_unit_vector(30, dim)
        return make_unit_vector(200, dim)

    async def fake_synthesize_answer(query: str, chunks: list[RetrievedChunk]) -> str:
        if not chunks:
            return NO_ACCESSIBLE_INFO_MESSAGE
        titles = {c.document_title for c in chunks}
        if "Helios" in query and "Org A Project Helios" not in titles:
            # Simulates Groq ignoring the L1 injection trap and returning neutral fallback
            return NO_ACCESSIBLE_INFO_MESSAGE
        top = chunks[0]
        return f"Grounded summary from [{top.document_title} | {top.classification_tag}]."

    monkeypatch.setattr("app.api.routes.embed_query", fake_embed_query)
    monkeypatch.setattr("app.api.routes.synthesize_answer", fake_synthesize_answer)

    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            tok_l1 = await _get_token(client, isolated_world.email_a_l1)
            tok_l4 = await _get_token(client, isolated_world.email_a_l4)
            tok_b4 = await _get_token(client, isolated_world.email_b_l4)

            # 1. L1 asks allowed L1 question
            ok_res = await client.post(
                "/api/v1/query",
                headers={"Authorization": f"Bearer {tok_l1}"},
                json={"query": "What is the remote work and PTO policy?"},
            )
            assert ok_res.status_code == 200
            ok_body = ok_res.json()
            assert "Org A Handbook | L1_PUBLIC" in ok_body["answer"]
            assert [c["document_title"] for c in ok_body["citations"]] == ["Org A Handbook"]
            assert ok_body["trace"]["rls_context"]["clearance_level"] == 1

            # 2. L1 asks about Project Helios -> neutral fallback & citations suppressed
            blocked_res = await client.post(
                "/api/v1/query",
                headers={"Authorization": f"Bearer {tok_l1}"},
                json={"query": "What is Project Helios?"},
            )
            assert blocked_res.status_code == 200
            blocked_body = blocked_res.json()
            assert blocked_body["answer"] == NO_ACCESSIBLE_INFO_MESSAGE
            assert blocked_body["citations"] == []

            # 3. L4 asks about Project Helios -> gets Org A L4 citation
            vp_res = await client.post(
                "/api/v1/query",
                headers={"Authorization": f"Bearer {tok_l4}"},
                json={"query": "What is Project Helios?"},
            )
            assert vp_res.status_code == 200
            assert vp_res.json()["citations"][0]["document_title"] == "Org A Project Helios"

            # 4. Secure citation proxy (/view): L4 succeeds, L1 & Org B get 404
            view_l4 = await client.get(
                f"/api/v1/documents/{isolated_world.doc_a_l4}/view",
                headers={"Authorization": f"Bearer {tok_l4}"},
            )
            assert view_l4.status_code == 200
            assert view_l4.json()["document"]["title"] == "Org A Project Helios"

            view_l1 = await client.get(
                f"/api/v1/documents/{isolated_world.doc_a_l4}/view",
                headers={"Authorization": f"Bearer {tok_l1}"},
            )
            assert view_l1.status_code == 404

            view_b4 = await client.get(
                f"/api/v1/documents/{isolated_world.doc_a_l4}/view",
                headers={"Authorization": f"Bearer {tok_b4}"},
            )
            assert view_b4.status_code == 404

            # 5. Audit logs are strictly tenant-isolated
            audit_a = await client.get(
                "/api/v1/audit", headers={"Authorization": f"Bearer {tok_l4}"}
            )
            audit_b = await client.get(
                "/api/v1/audit", headers={"Authorization": f"Bearer {tok_b4}"}
            )
            assert len(audit_a.json()["audit_logs"]) == 3
            assert audit_b.json()["audit_logs"] == []
    finally:
        await close_db_pool()
