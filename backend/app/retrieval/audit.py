"""Secure document citation proxy and tenant-isolated audit log helpers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.db import RLSContext, scoped_rls_transaction


async def get_accessible_document_detail(
    ctx: RLSContext,
    document_id: UUID,
) -> dict[str, Any] | None:
    """Return document metadata and ordered chunks strictly under RLS enforcement."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, org_id, title, department, clearance_level,
                   classification_tag, source_uri, created_at, updated_at
            FROM documents
            WHERE id = %s
            """,
            (document_id,),
        )
        doc_row = await cur.fetchone()
        if doc_row is None:
            return None

        await cur.execute(
            """
            SELECT id, chunk_index, content
            FROM document_chunks
            WHERE document_id = %s
            ORDER BY chunk_index ASC
            """,
            (document_id,),
        )
        chunk_rows = await cur.fetchall()

    return {
        "id": str(doc_row[0]),
        "org_id": str(doc_row[1]),
        "title": doc_row[2],
        "department": doc_row[3],
        "clearance_level": doc_row[4],
        "classification_tag": doc_row[5],
        "source_uri": doc_row[6],
        "created_at": doc_row[7].isoformat(),
        "updated_at": doc_row[8].isoformat(),
        "chunks": [
            {"chunk_id": str(row[0]), "chunk_index": row[1], "content": row[2]}
            for row in chunk_rows
        ],
    }


async def log_query_audit(
    ctx: RLSContext,
    *,
    query_text: str,
    retrieved_doc_ids: list[UUID],
    latency_ms: int,
) -> None:
    """Persist an audit log entry inside an RLS-scoped transaction."""
    unique_doc_ids = list(dict.fromkeys(retrieved_doc_ids))
    async with scoped_rls_transaction(ctx) as conn:
        await conn.execute(
            """
            INSERT INTO audit_logs
                (org_id, user_id, user_clearance, query_text, retrieved_doc_ids, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                ctx.org_id,
                ctx.user_id,
                ctx.clearance_level,
                query_text,
                unique_doc_ids,
                latency_ms,
            ),
        )


async def list_audit_logs(ctx: RLSContext, limit: int = 25) -> list[dict[str, Any]]:
    """Return recent tenant-isolated audit log entries under PostgreSQL RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, org_id, user_id, user_clearance, query_text,
                   retrieved_doc_ids, latency_ms, created_at
            FROM audit_logs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()

    return [
        {
            "id": str(row[0]),
            "org_id": str(row[1]),
            "user_id": str(row[2]),
            "user_clearance": row[3],
            "query_text": row[4],
            "retrieved_doc_ids": [str(doc_id) for doc_id in row[5]],
            "latency_ms": row[6],
            "created_at": row[7].isoformat(),
        }
        for row in rows
    ]
