"""Database persistence for document ingestion, RLS-scoped listing, and O(1) reclassification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.errors import InsufficientPrivilege

from app.core.db import RLSContext, get_db_pool, scoped_rls_transaction
from app.core.quotas import enforce_document_quota
from app.ingestion.chunker import chunk_text
from app.ingestion.embedder import embed_documents

CLASSIFICATION_TAGS: dict[int, str] = {
    1: "L1_PUBLIC",
    2: "L2_INTERNAL",
    3: "L3_CONFIDENTIAL",
    4: "L4_EXECUTIVE",
}


class ClearanceViolationError(PermissionError):
    """Raised when a user attempts to assign a clearance level above their own."""


@dataclass(frozen=True)
class DocumentRecord:
    """Serialized document metadata returned by API routes."""

    id: UUID
    org_id: UUID
    title: str
    department: str
    clearance_level: int
    classification_tag: str
    source_uri: str
    created_at: datetime
    updated_at: datetime
    chunk_count: int | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Convert record to JSON-serializable dict."""
        data: dict[str, Any] = {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "title": self.title,
            "department": self.department,
            "clearance_level": self.clearance_level,
            "classification_tag": self.classification_tag,
            "source_uri": self.source_uri,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        if self.chunk_count is not None:
            data["chunk_count"] = self.chunk_count
        return data


def classification_tag_for(clearance_level: int) -> str:
    """Resolve canonical classification tag for clearance level 1..4."""
    if clearance_level not in CLASSIFICATION_TAGS:
        raise ValueError("clearance_level must be between 1 and 4")
    return CLASSIFICATION_TAGS[clearance_level]


async def insert_document_with_chunks(
    conn: AsyncConnection,
    *,
    org_id: UUID,
    title: str,
    department: str,
    clearance_level: int,
    source_uri: str,
    chunks: list[str],
    embeddings: list[list[float]],
    storage_key: str | None = None,
    replace_existing: bool = False,
) -> DocumentRecord:
    """Insert or replace (version-bump) a document and its chunks inside a transaction."""
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings count must match")

    tag = classification_tag_for(clearance_level)

    async with conn.cursor() as cur:
        existing_id: UUID | None = None
        if replace_existing:
            await cur.execute(
                "SELECT id FROM documents WHERE org_id = %s AND title = %s LIMIT 1",
                (org_id, title),
            )
            existing_row = await cur.fetchone()
            if existing_row is not None:
                existing_id = existing_row[0]

        if existing_id is not None:
            doc_id = existing_id
            await cur.execute(
                """
                UPDATE documents
                SET department = %s,
                    clearance_level = %s,
                    classification_tag = %s,
                    source_uri = %s,
                    storage_key = COALESCE(%s, storage_key),
                    version = version + 1,
                    updated_at = now()
                WHERE id = %s
                RETURNING id, org_id, title, department, clearance_level,
                          classification_tag, source_uri, created_at, updated_at, version
                """,
                (department, clearance_level, tag, source_uri, storage_key, doc_id),
            )
            row = await cur.fetchone()
            await cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (doc_id,))
        else:
            doc_id = uuid4()
            await cur.execute(
                """
                INSERT INTO documents
                    (id, org_id, title, department, clearance_level,
                     classification_tag, source_uri, storage_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, org_id, title, department, clearance_level,
                          classification_tag, source_uri, created_at, updated_at, version
                """,
                (doc_id, org_id, title, department, clearance_level, tag, source_uri, storage_key),
            )
            row = await cur.fetchone()

        if row is None:
            raise RuntimeError("Failed to persist document row.")

        chunk_rows = [
            (uuid4(), org_id, doc_id, idx, chunk, vector)
            for idx, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=True))
        ]
        await cur.executemany(
            """
            INSERT INTO document_chunks (id, org_id, document_id, chunk_index, content, embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            chunk_rows,
        )

    return DocumentRecord(
        id=row[0],
        org_id=row[1],
        title=row[2],
        department=row[3],
        clearance_level=row[4],
        classification_tag=row[5],
        source_uri=row[6],
        created_at=row[7],
        updated_at=row[8],
        chunk_count=len(chunk_rows),
        version=int(row[9]),
    )


def validate_write_scope(ctx: RLSContext, *, clearance_level: int, department: str) -> None:
    """Enforce clearance and L3/L4 department write boundaries before DB transaction."""
    if clearance_level > ctx.clearance_level:
        raise ClearanceViolationError(
            "Cannot write or classify a document above your own clearance level."
        )
    if (
        clearance_level >= 3
        and not ctx.is_org_admin
        and department not in ("General", ctx.department)
    ):
        raise ClearanceViolationError(
            "Non-admins cannot assign L3/L4 documents to another department."
        )


async def ingest_document(
    ctx: RLSContext,
    *,
    title: str,
    department: str,
    clearance_level: int,
    content: str,
    source_uri: str,
    storage_key: str | None = None,
    replace_existing: bool = False,
) -> DocumentRecord:
    """Chunk text, generate Gemini embeddings, and persist under RLS enforcement."""
    validate_write_scope(ctx, clearance_level=clearance_level, department=department)

    if not replace_existing:
        await enforce_document_quota(ctx)
    else:
        async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM documents WHERE org_id = %s AND title = %s LIMIT 1",
                (ctx.org_id, title),
            )
            exists = await cur.fetchone() is not None
        if not exists:
            await enforce_document_quota(ctx)

    chunks = chunk_text(content)
    if not chunks:
        raise ValueError("Document contains no extractable text.")

    embeddings = await embed_documents(chunks)

    try:
        async with scoped_rls_transaction(ctx) as conn:
            return await insert_document_with_chunks(
                conn,
                org_id=ctx.org_id,
                title=title,
                department=department,
                clearance_level=clearance_level,
                source_uri=source_uri,
                chunks=chunks,
                embeddings=embeddings,
                storage_key=storage_key,
                replace_existing=replace_existing,
            )
    except InsufficientPrivilege as exc:
        raise ClearanceViolationError(
            "Database RLS rejected document write above caller clearance."
        ) from exc


async def list_accessible_documents(ctx: RLSContext) -> list[DocumentRecord]:
    """List documents visible to ctx under PostgreSQL RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT d.id, d.org_id, d.title, d.department, d.clearance_level,
                   d.classification_tag, d.source_uri, d.created_at, d.updated_at,
                   COUNT(c.id)::int AS chunk_count, d.version
            FROM documents d
            LEFT JOIN document_chunks c ON c.document_id = d.id
            GROUP BY d.id
            ORDER BY d.clearance_level DESC, d.created_at DESC
            """
        )
        rows = await cur.fetchall()

    return [
        DocumentRecord(
            id=row[0],
            org_id=row[1],
            title=row[2],
            department=row[3],
            clearance_level=row[4],
            classification_tag=row[5],
            source_uri=row[6],
            created_at=row[7],
            updated_at=row[8],
            chunk_count=row[9],
            version=int(row[10]),
        )
        for row in rows
    ]


async def reclassify_document(
    ctx: RLSContext,
    *,
    document_id: UUID,
    new_clearance_level: int,
    new_department: str | None = None,
) -> DocumentRecord | None:
    """Update document clearance and/or department in O(1) without re-embedding."""
    validate_write_scope(
        ctx,
        clearance_level=new_clearance_level,
        department=new_department if new_department is not None else ctx.department,
    )

    new_tag = classification_tag_for(new_clearance_level)

    try:
        async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE documents
                SET clearance_level = %s,
                    classification_tag = %s,
                    department = COALESCE(%s, department),
                    updated_at = now()
                WHERE id = %s
                RETURNING id, org_id, title, department, clearance_level,
                          classification_tag, source_uri, created_at, updated_at
                """,
                (
                    new_clearance_level,
                    new_tag,
                    new_department.strip() if new_department else None,
                    document_id,
                ),
            )
            row = await cur.fetchone()
    except InsufficientPrivilege as exc:
        raise ClearanceViolationError(
            "Database RLS rejected reclassification above caller scope."
        ) from exc

    if row is None:
        return None

    return DocumentRecord(
        id=row[0],
        org_id=row[1],
        title=row[2],
        department=row[3],
        clearance_level=row[4],
        classification_tag=row[5],
        source_uri=row[6],
        created_at=row[7],
        updated_at=row[8],
    )


async def delete_document(ctx: RLSContext, *, document_id: UUID) -> bool:
    """Delete a document (cascading to chunks) inside an RLS-scoped transaction."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM documents WHERE id = %s RETURNING id",
            (document_id,),
        )
        return (await cur.fetchone()) is not None


async def list_demo_personas() -> list[dict[str, Any]]:
    """Return seeded organization users for demo persona switching."""
    pool = get_db_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT u.id, u.org_id, o.name, o.slug, u.email, u.full_name,
                   u.role_title, u.department, u.clearance_level,
                   u.is_org_admin, u.token_version
            FROM users u
            JOIN organizations o ON o.id = u.org_id
            WHERE u.is_active = true
            ORDER BY o.name ASC, u.clearance_level ASC
            """
        )
        rows = await cur.fetchall()

    return [
        {
            "user_id": str(row[0]),
            "org_id": str(row[1]),
            "org_name": row[2],
            "org_slug": row[3],
            "email": row[4],
            "full_name": row[5],
            "role_title": row[6],
            "department": row[7],
            "clearance_level": row[8],
            "is_org_admin": row[9],
            "token_version": row[10],
        }
        for row in rows
    ]


async def get_persona_by_email(email: str) -> dict[str, Any] | None:
    """Look up a single seeded persona by email."""
    pool = get_db_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT u.id, u.org_id, o.name, o.slug, u.email, u.full_name,
                   u.role_title, u.department, u.clearance_level,
                   u.is_org_admin, u.token_version
            FROM users u
            JOIN organizations o ON o.id = u.org_id
            WHERE u.email = %s AND u.is_active = true
            """,
            (email,),
        )
        row = await cur.fetchone()

    if row is None:
        return None

    return {
        "user_id": row[0],
        "org_id": row[1],
        "org_name": row[2],
        "org_slug": row[3],
        "email": row[4],
        "full_name": row[5],
        "role_title": row[6],
        "department": row[7],
        "clearance_level": row[8],
        "is_org_admin": row[9],
        "token_version": row[10],
    }
