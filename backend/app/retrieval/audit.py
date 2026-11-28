"""Secure document citation proxy, stitched reader, conversation history, and audit logs."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.db import RLSContext, scoped_rls_transaction


def _stitch_chunks(contents: list[str]) -> str:
    """Merge overlapping sequential chunks into one seamless readable document."""
    if not contents:
        return ""
    stitched = contents[0]
    for nxt in contents[1:]:
        max_overlap = min(len(stitched), len(nxt), 200)
        overlap_len = 0
        for candidate in range(max_overlap, 15, -1):
            if stitched.endswith(nxt[:candidate]):
                overlap_len = candidate
                break
        if overlap_len > 0:
            stitched += nxt[overlap_len:]
        else:
            stitched += "\n\n" + nxt
    return stitched


async def get_accessible_document_detail(
    ctx: RLSContext,
    document_id: UUID,
) -> dict[str, Any] | None:
    """Return document metadata, stitched full_text, and chunks strictly under RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, org_id, title, department, clearance_level,
                   classification_tag, source_uri, version, storage_key,
                   created_at, updated_at
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

    chunk_texts = [row[2] for row in chunk_rows]
    return {
        "id": str(doc_row[0]),
        "org_id": str(doc_row[1]),
        "title": doc_row[2],
        "department": doc_row[3],
        "clearance_level": doc_row[4],
        "classification_tag": doc_row[5],
        "source_uri": doc_row[6],
        "version": doc_row[7],
        "has_download": bool(doc_row[8]),
        "storage_key": doc_row[8],
        "created_at": doc_row[9].isoformat(),
        "updated_at": doc_row[10].isoformat(),
        "full_text": _stitch_chunks(chunk_texts),
        "chunks": [
            {"chunk_id": str(row[0]), "chunk_index": row[1], "content": row[2]}
            for row in chunk_rows
        ],
    }


async def create_or_get_conversation(
    ctx: RLSContext,
    *,
    conversation_id: UUID | None,
    first_query: str,
) -> UUID:
    """Ensure a user-owned conversation row exists under RLS."""
    title = first_query.strip()[:80] or "New Conversation"
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        if conversation_id is not None:
            await cur.execute(
                "SELECT id FROM conversations WHERE id = %s",
                (conversation_id,),
            )
            if await cur.fetchone() is not None:
                return conversation_id

        await cur.execute(
            """
            INSERT INTO conversations (org_id, user_id, title)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (ctx.org_id, ctx.user_id, title),
        )
        row = await cur.fetchone()
        assert row is not None
        return row[0]


async def append_conversation_turn(
    ctx: RLSContext,
    *,
    conversation_id: UUID,
    query_text: str,
    answer_text: str,
    citations: list[dict[str, object]],
) -> None:
    """Append user + assistant messages to a conversation under RLS."""
    async with scoped_rls_transaction(ctx) as conn:
        await conn.execute(
            """
            INSERT INTO messages (conversation_id, org_id, user_id, role, content, citations_json)
            VALUES
                (%s, %s, %s, 'user', %s, '[]'::jsonb),
                (%s, %s, %s, 'assistant', %s, %s::jsonb)
            """,
            (
                conversation_id,
                ctx.org_id,
                ctx.user_id,
                query_text,
                conversation_id,
                ctx.org_id,
                ctx.user_id,
                answer_text,
                json.dumps(citations),
            ),
        )
        await conn.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = %s",
            (conversation_id,),
        )


async def list_conversations(ctx: RLSContext, limit: int = 30) -> list[dict[str, Any]]:
    """List conversations belonging strictly to the caller under RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()
    return [
        {
            "id": str(row[0]),
            "title": row[1],
            "created_at": row[2].isoformat(),
            "updated_at": row[3].isoformat(),
        }
        for row in rows
    ]


async def get_conversation_detail(
    ctx: RLSContext,
    conversation_id: UUID,
) -> dict[str, Any] | None:
    """Return a conversation and its ordered messages strictly under RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = %s",
            (conversation_id,),
        )
        conv = await cur.fetchone()
        if conv is None:
            return None

        await cur.execute(
            """
            SELECT id, role, content, citations_json, created_at
            FROM messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        )
        msgs = await cur.fetchall()

    return {
        "id": str(conv[0]),
        "title": conv[1],
        "created_at": conv[2].isoformat(),
        "updated_at": conv[3].isoformat(),
        "messages": [
            {
                "id": str(m[0]),
                "role": m[1],
                "content": m[2],
                "citations": m[3],
                "created_at": m[4].isoformat(),
            }
            for m in msgs
        ],
    }


async def delete_conversation(ctx: RLSContext, conversation_id: UUID) -> bool:
    """Delete a user's conversation under RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM conversations WHERE id = %s RETURNING id",
            (conversation_id,),
        )
        return (await cur.fetchone()) is not None


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
            SELECT a.id, a.org_id, a.user_id, a.user_clearance, a.query_text,
                   a.retrieved_doc_ids, a.latency_ms, a.created_at,
                   u.full_name, u.email
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            ORDER BY a.created_at DESC
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
            "user_name": row[8],
            "user_email": row[9],
        }
        for row in rows
    ]
