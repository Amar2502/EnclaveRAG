"""Phase UX-1 integration tests: streaming, conversations RLS, versioning, download, invites."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from pathlib import Path

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


async def test_document_versioning_download_and_suggestions(
    isolated_world: IsolatedTestWorld,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Uploading the same title with replace_existing=True bumps version; download enforces RLS."""
    dim = settings.embedding_dimension

    async def fake_embed_documents(texts: list[str]) -> list[list[float]]:
        return [make_unit_vector(300 + i, dim) for i in range(len(texts))]

    monkeypatch.setattr(settings, "storage_provider", "local")
    monkeypatch.setattr(settings, "local_storage_dir", str(tmp_path))
    monkeypatch.setattr("app.ingestion.service.embed_documents", fake_embed_documents)

    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            tok_a4 = await _get_token(client, isolated_world.email_a_l4)
            tok_a1 = await _get_token(client, isolated_world.email_a_l1)
            tok_b4 = await _get_token(client, isolated_world.email_b_l4)

            up1 = await client.post(
                "/api/v1/documents/upload",
                headers={"Authorization": f"Bearer {tok_a4}"},
                data={
                    "title": "Security Handbook",
                    "clearance_level": "3",
                    "department": "Engineering",
                    "replace_existing": "true",
                },
                files={"file": ("handbook.txt", b"Version one content.", "text/plain")},
            )
            assert up1.status_code == 201
            doc1 = up1.json()["document"]
            assert doc1["version"] == 1

            up2 = await client.post(
                "/api/v1/documents/upload",
                headers={"Authorization": f"Bearer {tok_a4}"},
                data={
                    "title": "Security Handbook",
                    "clearance_level": "3",
                    "department": "Engineering",
                    "replace_existing": "true",
                },
                files={"file": ("handbook.txt", b"Version two updated content.", "text/plain")},
            )
            assert up2.status_code == 201
            doc2 = up2.json()["document"]
            assert doc2["id"] == doc1["id"]
            assert doc2["version"] == 2

            view_res = await client.get(
                f"/api/v1/documents/{doc2['id']}/view",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert view_res.status_code == 200
            assert "Version two updated content." in view_res.json()["document"]["full_text"]
            assert view_res.json()["document"]["has_download"] is True

            dl_ok = await client.get(
                f"/api/v1/documents/{doc2['id']}/download",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert dl_ok.status_code == 200
            assert dl_ok.content == b"Version two updated content."

            # L1 in same org and L4 in other org must receive 404 (zero existence leakage).
            dl_l1 = await client.get(
                f"/api/v1/documents/{doc2['id']}/download",
                headers={"Authorization": f"Bearer {tok_a1}"},
            )
            assert dl_l1.status_code == 404

            dl_b4 = await client.get(
                f"/api/v1/documents/{doc2['id']}/download",
                headers={"Authorization": f"Bearer {tok_b4}"},
            )
            assert dl_b4.status_code == 404

            sugg_a4 = await client.get(
                "/api/v1/suggestions",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert sugg_a4.status_code == 200
            assert any("Security Handbook" in s for s in sugg_a4.json()["suggestions"])

            # L1 must not receive L3 Security Handbook in suggestions
            sugg_a1 = await client.get(
                "/api/v1/suggestions",
                headers={"Authorization": f"Bearer {tok_a1}"},
            )
            assert sugg_a1.status_code == 200
            assert not any("Security Handbook" in s for s in sugg_a1.json()["suggestions"])
    finally:
        await close_db_pool()


async def test_streaming_query_and_conversations_user_rls(
    isolated_world: IsolatedTestWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SSE /query/stream persists conversations isolated per user_id via RLS."""
    dim = settings.embedding_dimension
    reset_rate_limiter()

    async def fake_embed_query(text: str) -> list[float]:
        return make_unit_vector(310, dim)

    async def fake_embed_documents(texts: list[str]) -> list[list[float]]:
        return [make_unit_vector(310, dim) for _ in texts]

    async def fake_stream(
        query: str,
        chunks: list[RetrievedChunk],
        history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        assert chunks
        yield "Hello "
        yield "**world**"

    monkeypatch.setattr("app.api.routes.embed_query", fake_embed_query)
    monkeypatch.setattr("app.ingestion.service.embed_documents", fake_embed_documents)
    monkeypatch.setattr("app.api.routes.synthesize_answer_stream", fake_stream)

    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            tok_a4 = await _get_token(client, isolated_world.email_a_l4)
            tok_a1 = await _get_token(client, isolated_world.email_a_l1)

            ingest_res = await client.post(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {tok_a4}"},
                json={
                    "title": "Public FAQ",
                    "department": "General",
                    "clearance_level": 1,
                    "content": "Employees get 20 days of PTO annually.",
                },
            )
            assert ingest_res.status_code == 201

            stream_res = await client.post(
                "/api/v1/query/stream",
                headers={"Authorization": f"Bearer {tok_a4}"},
                json={"query": "How much PTO do employees get?", "top_k": 3},
            )
            assert stream_res.status_code == 200
            body = stream_res.text
            assert "event: token" in body
            assert "event: done" in body

            done_line = [ln for ln in body.splitlines() if ln.startswith("data: ")][-1]
            done_data = json.loads(done_line.removeprefix("data: "))
            assert done_data["answer"] == "Hello **world**"
            conv_id = done_data["conversation_id"]

            # Owner can list and read the conversation
            list_a4 = await client.get(
                "/api/v1/conversations",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert list_a4.status_code == 200
            assert any(c["id"] == conv_id for c in list_a4.json()["conversations"])

            detail_a4 = await client.get(
                f"/api/v1/conversations/{conv_id}",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert detail_a4.status_code == 200
            assert len(detail_a4.json()["conversation"]["messages"]) == 2

            # Another user in the same org cannot see or delete A4's conversation
            list_a1 = await client.get(
                "/api/v1/conversations",
                headers={"Authorization": f"Bearer {tok_a1}"},
            )
            assert list_a1.status_code == 200
            assert not any(c["id"] == conv_id for c in list_a1.json()["conversations"])

            detail_a1 = await client.get(
                f"/api/v1/conversations/{conv_id}",
                headers={"Authorization": f"Bearer {tok_a1}"},
            )
            assert detail_a1.status_code == 404

            del_a4 = await client.delete(
                f"/api/v1/conversations/{conv_id}",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert del_a4.status_code == 200
    finally:
        await close_db_pool()


async def test_admin_invite_resend_and_cancel(isolated_world: IsolatedTestWorld) -> None:
    """Org admins can resend and cancel pending invitations."""
    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            tok_a4 = await _get_token(client, isolated_world.email_a_l4)

            create_res = await client.post(
                "/api/v1/admin/invites",
                headers={"Authorization": f"Bearer {tok_a4}"},
                json={
                    "email": "ux_invitee@example.com",
                    "clearance_level": 2,
                    "department": "Engineering",
                },
            )
            assert create_res.status_code == 201
            invite_id = create_res.json()["invite"]["id"]

            resend_res = await client.post(
                f"/api/v1/admin/invites/{invite_id}/resend",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert resend_res.status_code == 200
            assert "invite_url" in resend_res.json()["invite"]

            del_res = await client.delete(
                f"/api/v1/admin/invites/{invite_id}",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert del_res.status_code == 200
            assert del_res.json()["status"] == "cancelled"
    finally:
        await close_db_pool()
