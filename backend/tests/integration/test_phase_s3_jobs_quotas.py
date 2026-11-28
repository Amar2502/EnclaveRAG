"""Phase S3 integration tests: ObjectStore, async ingestion jobs, quotas, rate limits, billing."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.db import close_db_pool, init_db_pool
from app.core.quotas import reset_rate_limiter
from app.llm.synthesizer import NO_ACCESSIBLE_INFO_MESSAGE
from app.main import app
from app.retrieval.hybrid_search import RetrievedChunk
from app.storage.store import LocalObjectStore, S3ObjectStore
from tests.conftest import IsolatedTestWorld, make_unit_vector


async def _get_token(client: AsyncClient, email: str) -> str:
    res = await client.post("/api/v1/auth/persona-token", json={"email": email})
    assert res.status_code == 200
    return str(res.json()["access_token"])


async def test_local_object_store_and_s3_validation(tmp_path: Path) -> None:
    """LocalObjectStore persists/deletes safely and rejects path traversal."""
    store = LocalObjectStore(tmp_path)
    await store.put_bytes("orgs/a/file.txt", b"hello enclave")
    assert await store.get_bytes("orgs/a/file.txt") == b"hello enclave"
    await store.delete_bytes("orgs/a/file.txt")
    assert not (tmp_path / "orgs/a/file.txt").exists()

    with pytest.raises(ValueError, match="Invalid storage key"):
        await store.put_bytes("../../escape.txt", b"bad")

    with pytest.raises(RuntimeError, match="S3 storage credentials"):
        S3ObjectStore(
            endpoint_url="",
            access_key_id="",
            secret_access_key="",
            bucket_name="",
        )


async def test_async_upload_job_and_cross_org_job_isolation(
    isolated_world: IsolatedTestWorld,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """POST /documents/upload-async enqueues, processes to indexed, and isolates jobs by org."""
    dim = settings.embedding_dimension

    async def fake_embed_documents(texts: list[str]) -> list[list[float]]:
        return [make_unit_vector(210 + i, dim) for i in range(len(texts))]

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
            tok_b4 = await _get_token(client, isolated_world.email_b_l4)

            upload_res = await client.post(
                "/api/v1/documents/upload-async",
                headers={"Authorization": f"Bearer {tok_a4}"},
                data={"clearance_level": "2", "department": "Engineering"},
                files={
                    "file": (
                        "async_spec.md",
                        b"# Async Pipeline\n\nIndexed via background job.",
                        "text/markdown",
                    )
                },
            )
            assert upload_res.status_code == 202
            job_id = upload_res.json()["job"]["id"]

            # BackgroundTasks executes before returning/awaiting in ASGITransport or right after
            status_res = await client.get(
                f"/api/v1/jobs/{job_id}",
                headers={"Authorization": f"Bearer {tok_a4}"},
            )
            assert status_res.status_code == 200
            assert status_res.json()["job"]["status"] == "indexed"
            assert status_res.json()["job"]["document_id"] is not None

            # Cross-org tenant cannot see Org A's job (404)
            cross_org_job = await client.get(
                f"/api/v1/jobs/{job_id}",
                headers={"Authorization": f"Bearer {tok_b4}"},
            )
            assert cross_org_job.status_code == 404
    finally:
        await close_db_pool()


async def test_quotas_rate_limit_and_stripe_webhook(
    isolated_world: IsolatedTestWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enforce document quota (402), query quota & rate limit (429), and Stripe upgrades."""
    dim = settings.embedding_dimension
    reset_rate_limiter()

    async def fake_embed_query(_query: str) -> list[float]:
        return make_unit_vector(200, dim)

    async def fake_synthesize_answer(_query: str, _chunks: list[RetrievedChunk]) -> str:
        return NO_ACCESSIBLE_INFO_MESSAGE

    monkeypatch.setattr("app.api.routes.embed_query", fake_embed_query)
    monkeypatch.setattr("app.api.routes.synthesize_answer", fake_synthesize_answer)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret")

    # Set tight plan limits on Org A: max_documents=4 (already has 4), monthly_query_limit=1
    async with await psycopg.AsyncConnection.connect(
        settings.admin_database_url,
        autocommit=True,
    ) as admin_conn:
        await admin_conn.execute(
            "UPDATE organizations SET max_documents = 4, monthly_query_limit = 1 WHERE id = %s",
            (isolated_world.org_a,),
        )

    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            tok_a4 = await _get_token(client, isolated_world.email_a_l4)
            headers = {"Authorization": f"Bearer {tok_a4}"}

            # 1. Document quota hit (402)
            doc_blocked = await client.post(
                "/api/v1/documents",
                headers=headers,
                json={
                    "title": "Over Quota",
                    "department": "Engineering",
                    "clearance_level": 2,
                    "content": "Should hit max_documents.",
                },
            )
            assert doc_blocked.status_code == 402

            # 2. First query succeeds (1/1), second hits monthly query quota (429)
            q1 = await client.post("/api/v1/query", headers=headers, json={"query": "hello"})
            assert q1.status_code == 200

            q2 = await client.post("/api/v1/query", headers=headers, json={"query": "hello again"})
            assert q2.status_code == 429

            # 3. Usage endpoint shows 1/1 queries and 4/4 documents
            usage_res = await client.get("/api/v1/billing/usage", headers=headers)
            assert usage_res.status_code == 200
            usage = usage_res.json()["usage"]
            assert usage["documents_count"] == 4
            assert usage["queries_used"] == 1

            # 4. Invalid Stripe webhook signature rejected (400)
            webhook_payload = json.dumps(
                {
                    "type": "checkout.session.completed",
                    "data": {
                        "object": {
                            "metadata": {
                                "org_id": str(isolated_world.org_a),
                                "plan_tier": "pro",
                            }
                        }
                    },
                }
            ).encode("utf-8")

            bad_hook = await client.post(
                "/api/v1/billing/webhook",
                content=webhook_payload,
                headers={"Stripe-Signature": "t=123,v1=bad"},
            )
            assert bad_hook.status_code == 400

            # 5. Valid Stripe webhook upgrades plan_tier -> pro (lifts limits)
            ts = "1700000000"
            sig = hmac.new(
                b"whsec_test_secret",
                f"{ts}.".encode() + webhook_payload,
                hashlib.sha256,
            ).hexdigest()
            good_hook = await client.post(
                "/api/v1/billing/webhook",
                content=webhook_payload,
                headers={"Stripe-Signature": f"t={ts},v1={sig}"},
            )
            assert good_hook.status_code == 200
            assert good_hook.json()["plan_tier"] == "pro"
            assert good_hook.json()["monthly_query_limit"] == 25000

            # Query succeeds again after Pro upgrade
            q3 = await client.post("/api/v1/query", headers=headers, json={"query": "after upgrade"})
            assert q3.status_code == 200

            # 6. Rate limiter blocks bursts exceeding org_rate_limit_per_min
            reset_rate_limiter()
            monkeypatch.setattr(settings, "org_rate_limit_per_min", 1)
            assert (
                await client.post("/api/v1/query", headers=headers, json={"query": "burst 1"})
            ).status_code == 200
            burst_2 = await client.post("/api/v1/query", headers=headers, json={"query": "burst 2"})
            assert burst_2.status_code == 429
            assert "Retry-After" in burst_2.headers
    finally:
        reset_rate_limiter()
        await close_db_pool()
