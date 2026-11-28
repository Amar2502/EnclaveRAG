"""PostgreSQL-backed async ingestion job queue and background processor."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.db import RLSContext, scoped_rls_transaction
from app.core.quotas import enforce_document_quota
from app.ingestion.chunker import SUPPORTED_EXTENSIONS, extract_text_from_upload
from app.ingestion.service import ingest_document, validate_write_scope
from app.storage.store import ObjectStore, build_storage_key, get_object_store


def _serialize_job(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "org_id": str(row[1]),
        "document_id": str(row[2]) if row[2] else None,
        "title": row[3],
        "department": row[4],
        "clearance_level": row[5],
        "filename": row[6],
        "storage_key": row[7],
        "status": row[8],
        "error_message": row[9],
        "created_at": row[10].isoformat(),
        "completed_at": row[11].isoformat() if row[11] else None,
    }


async def enqueue_ingestion_job(
    ctx: RLSContext,
    *,
    title: str,
    department: str,
    clearance_level: int,
    filename: str,
    content_bytes: bytes,
    content_type: str = "application/octet-stream",
    store: ObjectStore | None = None,
) -> dict[str, Any]:
    """Validate upload, persist bytes to object storage, and create a queued DB job."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    if not content_bytes:
        raise ValueError("Uploaded file is empty.")

    validate_write_scope(ctx, clearance_level=clearance_level, department=department)
    await enforce_document_quota(ctx)

    object_store = store or get_object_store()
    storage_key = build_storage_key(ctx.org_id, filename)
    await object_store.put_bytes(storage_key, content_bytes, content_type=content_type)

    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO ingestion_jobs
                (org_id, uploaded_by, title, department, clearance_level,
                 filename, storage_key, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued')
            RETURNING id, org_id, document_id, title, department, clearance_level,
                      filename, storage_key, status, error_message, created_at, completed_at
            """,
            (
                ctx.org_id,
                ctx.user_id,
                title,
                department,
                clearance_level,
                filename,
                storage_key,
            ),
        )
        row = await cur.fetchone()
        assert row is not None
        return _serialize_job(row)


async def process_ingestion_job(
    ctx: RLSContext,
    *,
    job_id: UUID,
    store: ObjectStore | None = None,
) -> dict[str, Any] | None:
    """Process a queued job: read raw file, chunk, Gemini-embed, and mark indexed."""
    object_store = store or get_object_store()

    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'processing'
            WHERE id = %s AND status = 'queued'
            RETURNING id, org_id, document_id, title, department, clearance_level,
                      filename, storage_key, status, error_message, created_at, completed_at
            """,
            (job_id,),
        )
        row = await cur.fetchone()

    if row is None:
        return None

    _, _, _, title, department, clearance_level, filename, storage_key, *_ = row

    try:
        raw_bytes = await object_store.get_bytes(storage_key)
        extracted = extract_text_from_upload(filename, raw_bytes)
        record = await ingest_document(
            ctx,
            title=title,
            department=department,
            clearance_level=int(clearance_level),
            content=extracted,
            source_uri=f"storage://{storage_key}",
        )
    # Catch all worker boundary failures (parsing, S3/Tigris, Gemini, DB) so the job
    # records 'failed' instead of remaining stuck in 'processing'.
    except Exception as exc:  # noqa: BLE001
        async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'failed',
                    error_message = %s,
                    completed_at = now()
                WHERE id = %s
                RETURNING id, org_id, document_id, title, department, clearance_level,
                          filename, storage_key, status, error_message, created_at, completed_at
                """,
                (str(exc)[:500], job_id),
            )
            failed_row = await cur.fetchone()
        return _serialize_job(failed_row) if failed_row else None

    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'indexed',
                document_id = %s,
                completed_at = now()
            WHERE id = %s
            RETURNING id, org_id, document_id, title, department, clearance_level,
                      filename, storage_key, status, error_message, created_at, completed_at
            """,
            (record.id, job_id),
        )
        done_row = await cur.fetchone()
    return _serialize_job(done_row) if done_row else None


async def get_ingestion_job(ctx: RLSContext, job_id: UUID) -> dict[str, Any] | None:
    """Fetch a single ingestion job under RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, org_id, document_id, title, department, clearance_level,
                   filename, storage_key, status, error_message, created_at, completed_at
            FROM ingestion_jobs
            WHERE id = %s
            """,
            (job_id,),
        )
        row = await cur.fetchone()
    return _serialize_job(row) if row else None


async def list_ingestion_jobs(ctx: RLSContext, limit: int = 25) -> list[dict[str, Any]]:
    """List recent ingestion jobs scoped to the caller's organization via RLS."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, org_id, document_id, title, department, clearance_level,
                   filename, storage_key, status, error_message, created_at, completed_at
            FROM ingestion_jobs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()
    return [_serialize_job(row) for row in rows]
