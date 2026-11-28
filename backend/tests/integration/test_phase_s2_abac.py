"""Phase S2 integration tests: Department ABAC + Clearance RLS and Admin Delete."""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.db import RLSContext, close_db_pool, init_db_pool
from app.core.security import create_access_token, hash_password
from app.main import app
from app.retrieval.hybrid_search import hybrid_rrf_search
from tests.conftest import IsolatedTestWorld, make_unit_vector


async def test_l3_department_abac_isolation_and_admin_reclassify(
    isolated_world: IsolatedTestWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L3 HR user cannot read or write L3 Security docs, while Org Admin can govern both."""
    dim = settings.embedding_dimension
    hr_user_id = uuid4()
    hr_email = f"hr-l3-{isolated_world.org_a}@test.local"

    async def fake_embed_documents(texts: list[str]) -> list[list[float]]:
        return [make_unit_vector(120 + i, dim) for i in range(len(texts))]

    monkeypatch.setattr("app.ingestion.service.embed_documents", fake_embed_documents)

    async with await psycopg.AsyncConnection.connect(
        settings.admin_database_url,
        autocommit=True,
    ) as admin_conn:
        await admin_conn.execute(
            """
            INSERT INTO users
                (id, org_id, email, full_name, role_title, department,
                 clearance_level, password_hash, is_org_admin, is_active, token_version)
            VALUES (%s, %s, %s, 'HR Director', 'HR Manager', 'HR', 3, %s, false, true, 1)
            """,
            (hr_user_id, isolated_world.org_a, hr_email, hash_password("HrSecret123!")),
        )

    hr_ctx = RLSContext(
        org_id=isolated_world.org_a,
        user_id=hr_user_id,
        clearance_level=3,
        department="HR",
        is_org_admin=False,
    )
    hr_token = create_access_token(hr_ctx)

    admin_token_res: str
    await init_db_pool()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            tok_res = await client.post(
                "/api/v1/auth/persona-token",
                json={"email": isolated_world.email_a_l4},
            )
            assert tok_res.status_code == 200
            admin_token_res = tok_res.json()["access_token"]

            # 1. L3 HR sees L1 & L2 company-wide docs, NOT L3 Security (Org A Vendor NDA)
            hr_docs = await client.get(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {hr_token}"},
            )
            assert hr_docs.status_code == 200
            hr_titles = {d["title"] for d in hr_docs.json()["documents"]}
            assert hr_titles == {"Org A Handbook", "Org A Engineering Roadmap"}

            # 2. Hybrid search as L3 HR using L3 Security's vector returns 0 Security chunks
            sec_search = await hybrid_rrf_search(
                hr_ctx,
                query="PrecisionDrive harmonic actuator discount",
                query_embedding=make_unit_vector(20, dim),
                top_k=5,
            )
            assert "Org A Vendor NDA" not in {c.document_title for c in sec_search.chunks}

            # 3. Direct /view on L3 Security doc returns 404 (no existence leakage)
            view_sec = await client.get(
                f"/api/v1/documents/{isolated_world.doc_a_l3}/view",
                headers={"Authorization": f"Bearer {hr_token}"},
            )
            assert view_sec.status_code == 404

            # 4. L3 HR cannot ingest an L3 document into Security (403)
            cross_dept_ingest = await client.post(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {hr_token}"},
                json={
                    "title": "Cross Dept Write",
                    "department": "Security",
                    "clearance_level": 3,
                    "content": "Should be rejected by ABAC scope.",
                },
            )
            assert cross_dept_ingest.status_code == 403

            # 5. L3 HR CAN ingest an L3 HR document
            hr_ingest = await client.post(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {hr_token}"},
                json={
                    "title": "HR Compensation Bands",
                    "department": "HR",
                    "clearance_level": 3,
                    "content": "L3 HR salary bands for Q4 hiring.",
                },
            )
            assert hr_ingest.status_code == 201
            hr_doc_id = hr_ingest.json()["document"]["id"]

            # 6. Org Admin reclassifies Org A Vendor NDA -> department HR in O(1)
            reclass = await client.patch(
                f"/api/v1/documents/{isolated_world.doc_a_l3}/classification",
                headers={"Authorization": f"Bearer {admin_token_res}"},
                json={"clearance_level": 3, "department": "HR"},
            )
            assert reclass.status_code == 200
            assert reclass.json()["document"]["department"] == "HR"

            # L3 HR immediately sees it
            hr_docs_after = await client.get(
                "/api/v1/documents",
                headers={"Authorization": f"Bearer {hr_token}"},
            )
            assert "Org A Vendor NDA" in {
                d["title"] for d in hr_docs_after.json()["documents"]
            }

            # 7. Non-admin cannot DELETE documents (403); Org Admin can (200)
            non_admin_del = await client.delete(
                f"/api/v1/documents/{hr_doc_id}",
                headers={"Authorization": f"Bearer {hr_token}"},
            )
            assert non_admin_del.status_code == 403

            admin_del = await client.delete(
                f"/api/v1/documents/{hr_doc_id}",
                headers={"Authorization": f"Bearer {admin_token_res}"},
            )
            assert admin_del.status_code == 200
    finally:
        await close_db_pool()
