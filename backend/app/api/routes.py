"""Phase 1-3 API routes (auth, ingestion, hybrid RRF query, citation proxy, audit trail)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.admin_routes import router as admin_router
from app.api.auth_routes import router as auth_router
from app.api.billing_routes import router as billing_router
from app.auth.service import get_org_clearance_labels
from app.core.config import settings
from app.core.db import RLSContext, scoped_rls_transaction
from app.core.quotas import (
    QuotaExceededError,
    RateLimitExceededError,
    check_and_increment_query_usage,
    enforce_org_rate_limit,
)
from app.core.security import (
    create_access_token,
    get_current_rls_context,
    require_org_admin,
)
from app.ingestion.chunker import extract_text_from_upload
from app.ingestion.embedder import embed_query
from app.ingestion.service import (
    ClearanceViolationError,
    delete_document,
    get_persona_by_email,
    ingest_document,
    list_accessible_documents,
    list_demo_personas,
    reclassify_document,
)
from app.ingestion.worker import (
    enqueue_ingestion_job,
    get_ingestion_job,
    list_ingestion_jobs,
    process_ingestion_job,
)
from app.llm.synthesizer import (
    NO_ACCESSIBLE_INFO_MESSAGE,
    synthesize_answer,
    synthesize_answer_stream,
)
from app.retrieval.audit import (
    append_conversation_turn,
    create_or_get_conversation,
    delete_conversation,
    get_accessible_document_detail,
    get_conversation_detail,
    list_audit_logs,
    list_conversations,
    log_query_audit,
)
from app.retrieval.hybrid_search import HybridRetrievalResult, hybrid_rrf_search
from app.storage.store import get_object_store

router = APIRouter()
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(billing_router)


def _ensure_demo_enabled() -> None:
    if not settings.enable_demo_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo endpoints are disabled in production mode.",
        )


class PersonaTokenRequest(BaseModel):
    """Request payload for issuing a demo persona JWT."""

    email: str


class IngestTextRequest(BaseModel):
    """JSON payload for ingesting raw text or markdown into EnclaveRAG."""

    title: str = Field(min_length=1, max_length=255)
    department: str = Field(default="General", min_length=1, max_length=100)
    clearance_level: int = Field(ge=1, le=4)
    content: str = Field(min_length=1)


class ReclassifyRequest(BaseModel):
    """Payload for O(1) document clearance and department updates."""

    clearance_level: int = Field(ge=1, le=4)
    department: str | None = Field(default=None, min_length=1, max_length=100)


class QueryRequest(BaseModel):
    """Payload for RLS-scoped hybrid RAG queries."""

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    history: list[dict[str, str]] | None = None
    conversation_id: UUID | None = None


@router.get("/personas", tags=["demo"])
async def get_personas() -> dict[str, list[dict[str, object]]]:
    """List seeded demo personas across organizations (dev demo mode only)."""
    _ensure_demo_enabled()
    personas = await list_demo_personas()
    return {"personas": personas}


@router.post("/auth/persona-token", tags=["demo"])
async def issue_persona_token(payload: PersonaTokenRequest) -> dict[str, object]:
    """Issue a signed JWT for a seeded demo persona (dev demo mode only)."""
    _ensure_demo_enabled()
    persona = await get_persona_by_email(payload.email)
    if persona is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Persona '{payload.email}' not found. Run db/seed/seed_data.py first.",
        )

    ctx = RLSContext(
        org_id=persona["org_id"],
        user_id=persona["user_id"],
        clearance_level=persona["clearance_level"],
        department=persona["department"],
        is_org_admin=bool(persona.get("is_org_admin", False)),
        token_version=int(persona.get("token_version", 1)),
    )
    token = create_access_token(ctx)
    clearance_labels = await get_org_clearance_labels(persona["org_id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "persona": {
            "user_id": str(persona["user_id"]),
            "org_id": str(persona["org_id"]),
            "org_name": persona["org_name"],
            "email": persona["email"],
            "full_name": persona["full_name"],
            "role_title": persona["role_title"],
            "department": persona["department"],
            "clearance_level": persona["clearance_level"],
            "is_org_admin": ctx.is_org_admin,
            "clearance_labels": clearance_labels,
        },
    }


@router.get("/whoami", tags=["auth"])
async def whoami(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Echo verified JWT claims alongside active PostgreSQL SET LOCAL session settings."""
    async with scoped_rls_transaction(ctx) as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT current_setting('app.org_id', true), "
            "current_setting('app.clearance_level', true), "
            "current_setting('app.user_id', true), "
            "current_setting('app.department', true), "
            "current_setting('app.is_org_admin', true)"
        )
        row = await cur.fetchone()

    db_org_id, db_clearance, db_user_id, db_dept, db_admin = (
        row if row else (None, None, None, None, None)
    )
    return {
        "jwt_claims": {
            "user_id": str(ctx.user_id),
            "org_id": str(ctx.org_id),
            "clearance_level": ctx.clearance_level,
            "department": ctx.department,
            "is_org_admin": ctx.is_org_admin,
        },
        "postgres_session": {
            "app.org_id": db_org_id,
            "app.clearance_level": int(db_clearance) if db_clearance else None,
            "app.user_id": db_user_id,
            "app.department": db_dept,
            "app.is_org_admin": db_admin == "true" if db_admin else False,
        },
    }


@router.get("/documents", tags=["documents"])
async def list_documents(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, list[dict[str, object]]]:
    """List documents visible to the caller under PostgreSQL RLS."""
    docs = await list_accessible_documents(ctx)
    return {"documents": [doc.to_dict() for doc in docs]}


async def _run_ingest(
    ctx: RLSContext,
    *,
    title: str,
    department: str,
    clearance_level: int,
    content: str,
    source_uri: str,
    storage_key: str | None = None,
    replace_existing: bool = False,
) -> dict[str, object]:
    """Shared ingestion handler translating domain/provider errors to HTTP errors."""
    try:
        record = await ingest_document(
            ctx,
            title=title,
            department=department,
            clearance_level=clearance_level,
            content=content,
            source_uri=source_uri,
            storage_key=storage_key,
            replace_existing=replace_existing,
        )
        return {"document": record.to_dict()}
    except ClearanceViolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except QuotaExceededError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {exc}",
        ) from exc


@router.post("/documents", status_code=status.HTTP_201_CREATED, tags=["documents"])
async def create_document(
    payload: IngestTextRequest,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Ingest raw text/markdown, generate Gemini embeddings, and store under RLS."""
    return await _run_ingest(
        ctx,
        title=payload.title,
        department=payload.department,
        clearance_level=payload.clearance_level,
        content=payload.content,
        source_uri="api://inline-text",
    )


@router.post("/documents/upload", status_code=status.HTTP_201_CREATED, tags=["documents"])
async def upload_document(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
    file: Annotated[UploadFile, File(...)],
    clearance_level: Annotated[int, Form(ge=1, le=4)],
    department: Annotated[str, Form()] = "General",
    title: Annotated[str | None, Form()] = None,
    replace_existing: Annotated[bool, Form()] = True,
) -> dict[str, object]:
    """Ingest an uploaded .txt, .md, or .pdf document under RLS."""
    raw_bytes = await file.read()
    filename = Path(file.filename or "uploaded.txt").name
    try:
        extracted = extract_text_from_upload(filename, raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    store = get_object_store()
    storage_key = f"{ctx.org_id}/{uuid4()}-{filename}"
    await store.put_bytes(
        storage_key,
        raw_bytes,
        content_type=file.content_type or "application/octet-stream",
    )

    return await _run_ingest(
        ctx,
        title=title or filename,
        department=department,
        clearance_level=clearance_level,
        content=extracted,
        source_uri=f"upload://{filename}",
        storage_key=storage_key,
        replace_existing=replace_existing,
    )


@router.post("/documents/upload-async", status_code=status.HTTP_202_ACCEPTED, tags=["documents"])
async def upload_document_async(
    background_tasks: BackgroundTasks,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
    file: Annotated[UploadFile, File(...)],
    clearance_level: Annotated[int, Form(ge=1, le=4)],
    department: Annotated[str, Form()] = "General",
    title: Annotated[str | None, Form()] = None,
    replace_existing: Annotated[bool, Form()] = True,
) -> dict[str, object]:
    """Store raw upload in object storage and process chunking/embeddings asynchronously."""
    raw_bytes = await file.read()
    filename = file.filename or "uploaded.txt"
    try:
        job = await enqueue_ingestion_job(
            ctx,
            title=title or filename,
            department=department,
            clearance_level=clearance_level,
            filename=filename,
            content_bytes=raw_bytes,
            content_type=file.content_type or "application/octet-stream",
            replace_existing=replace_existing,
        )
    except ClearanceViolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except QuotaExceededError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    background_tasks.add_task(process_ingestion_job, ctx, job_id=UUID(str(job["id"])))
    return {"job": job}


@router.get("/jobs", tags=["documents"])
async def list_jobs(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, list[dict[str, object]]]:
    """List ingestion jobs scoped to the caller's organization via RLS."""
    jobs = await list_ingestion_jobs(ctx, limit=limit)
    return {"jobs": jobs}


@router.get("/jobs/{job_id}", tags=["documents"])
async def get_job_status(
    job_id: UUID,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Poll status of a background ingestion job under RLS."""
    job = await get_ingestion_job(ctx, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return {"job": job}


@router.patch("/documents/{document_id}/classification", tags=["documents"])
async def update_document_classification(
    document_id: UUID,
    payload: ReclassifyRequest,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Reclassify a document in O(1) without re-embedding its chunks."""
    try:
        updated = await reclassify_document(
            ctx,
            document_id=document_id,
            new_clearance_level=payload.clearance_level,
            new_department=payload.department,
        )
    except ClearanceViolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    return {"document": updated.to_dict()}


@router.delete("/documents/{document_id}", tags=["documents"])
async def remove_document(
    document_id: UUID,
    ctx: Annotated[RLSContext, Depends(require_org_admin)],
) -> dict[str, str]:
    """Delete a document and its chunks (Org Admin only, tenant-scoped via RLS)."""
    deleted = await delete_document(ctx, document_id=document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return {"status": "deleted"}


@router.get("/documents/{document_id}/view", tags=["documents"])
async def view_document(
    document_id: UUID,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Secure citation proxy serving document chunks strictly under RLS."""
    doc = await get_accessible_document_detail(ctx, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return {"document": doc}


@router.get("/documents/{document_id}/download", tags=["documents"])
async def download_document(
    document_id: UUID,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> object:
    """Return a presigned download URL (Tigris/S3) or stream the local file under RLS."""
    doc = await get_accessible_document_detail(ctx, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    storage_key = doc.get("storage_key")
    if not storage_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original file is not available for download.",
        )

    store = get_object_store()
    presigned_url = store.generate_presigned_download_url(str(storage_key), expires_in=300)
    if presigned_url:
        return {"download_url": presigned_url, "expires_in": 300, "filename": doc["title"]}

    try:
        data = await store.get_bytes(str(storage_key))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original file not found in storage.",
        ) from exc

    safe_name = Path(str(storage_key)).name
    if len(safe_name) > 37 and safe_name[36] == "-":
        safe_name = safe_name[37:]
    return StreamingResponse(
        iter([data]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


async def _prepare_rag_query(
    payload: QueryRequest,
    ctx: RLSContext,
) -> tuple[float, int, HybridRetrievalResult]:
    """Enforce rate/quota limits, embed query, and run RLS-scoped hybrid RRF search."""
    try:
        enforce_org_rate_limit(ctx.org_id)
        await check_and_increment_query_usage(ctx)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc

    total_start = time.perf_counter()
    embed_start = time.perf_counter()
    try:
        query_embedding = await embed_query(payload.query)
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {exc}",
        ) from exc
    embed_ms = int((time.perf_counter() - embed_start) * 1000)

    retrieval = await hybrid_rrf_search(
        ctx,
        query=payload.query,
        query_embedding=query_embedding,
        top_k=payload.top_k,
    )
    return total_start, embed_ms, retrieval


def _build_citations(answer: str, retrieval: HybridRetrievalResult) -> list[dict[str, object]]:
    """Deduplicate cited documents when synthesis returns grounded content."""
    citations: list[dict[str, object]] = []
    if answer == NO_ACCESSIBLE_INFO_MESSAGE:
        return citations
    seen_docs: set[UUID] = set()
    for chunk in retrieval.chunks:
        if chunk.document_id not in seen_docs:
            seen_docs.add(chunk.document_id)
            citations.append(
                {
                    "document_id": str(chunk.document_id),
                    "document_title": chunk.document_title,
                    "department": chunk.department,
                    "clearance_level": chunk.clearance_level,
                    "classification_tag": chunk.classification_tag,
                }
            )
    return citations


def _build_trace(
    ctx: RLSContext,
    retrieval: HybridRetrievalResult,
    *,
    embed_ms: int,
    llm_ms: int,
    total_ms: int,
) -> dict[str, object]:
    """Format the retrieval and timing trace payload."""
    return {
        "rls_context": {
            "org_id": str(ctx.org_id),
            "user_id": str(ctx.user_id),
            "clearance_level": ctx.clearance_level,
            "department": ctx.department,
        },
        "retrieval": {
            "iterative_scan_enabled": retrieval.iterative_scan_enabled,
            "vector_candidates": retrieval.vector_candidates,
            "fts_candidates": retrieval.fts_candidates,
            "fused_count": len(retrieval.chunks),
            "chunks": [chunk.to_trace_dict() for chunk in retrieval.chunks],
        },
        "timings_ms": {
            "embed": embed_ms,
            "retrieval": retrieval.retrieval_ms,
            "llm": llm_ms,
            "total": total_ms,
        },
    }


@router.post("/query", tags=["rag"])
async def query_knowledge_base(
    payload: QueryRequest,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Execute RLS-scoped hybrid retrieval, Groq synthesis, and audit logging."""
    total_start, embed_ms, retrieval = await _prepare_rag_query(payload, ctx)

    llm_start = time.perf_counter()
    try:
        answer = await synthesize_answer(payload.query, retrieval.chunks, history=payload.history)
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Chat synthesis service error: {exc}",
        ) from exc
    llm_ms = int((time.perf_counter() - llm_start) * 1000)
    total_ms = int((time.perf_counter() - total_start) * 1000)

    citations = _build_citations(answer, retrieval)
    await log_query_audit(
        ctx,
        query_text=payload.query,
        retrieved_doc_ids=[chunk.document_id for chunk in retrieval.chunks],
        latency_ms=total_ms,
    )

    conv_id = await create_or_get_conversation(
        ctx,
        conversation_id=payload.conversation_id,
        first_query=payload.query,
    )
    await append_conversation_turn(
        ctx,
        conversation_id=conv_id,
        query_text=payload.query,
        answer_text=answer,
        citations=citations,
    )

    return {
        "answer": answer,
        "citations": citations,
        "conversation_id": str(conv_id),
        "trace": _build_trace(
            ctx, retrieval, embed_ms=embed_ms, llm_ms=llm_ms, total_ms=total_ms
        ),
    }


@router.post("/query/stream", tags=["rag"])
async def query_knowledge_base_stream(
    payload: QueryRequest,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> StreamingResponse:
    """Stream Groq tokens over SSE while enforcing RLS retrieval and conversation persistence."""
    total_start, embed_ms, retrieval = await _prepare_rag_query(payload, ctx)

    async def _event_stream() -> AsyncIterator[str]:
        llm_start = time.perf_counter()
        parts: list[str] = []
        try:
            async for token in synthesize_answer_stream(
                payload.query, retrieval.chunks, history=payload.history
            ):
                parts.append(token)
                yield f"event: token\ndata: {json.dumps({'text': token})}\n\n"
        except (RuntimeError, httpx.HTTPError) as exc:
            yield f"event: error\ndata: {json.dumps({'detail': f'Chat synthesis service error: {exc}'})}\n\n"
            return

        llm_ms = int((time.perf_counter() - llm_start) * 1000)
        total_ms = int((time.perf_counter() - total_start) * 1000)
        full_answer = "".join(parts).strip() or NO_ACCESSIBLE_INFO_MESSAGE
        citations = _build_citations(full_answer, retrieval)

        await log_query_audit(
            ctx,
            query_text=payload.query,
            retrieved_doc_ids=[chunk.document_id for chunk in retrieval.chunks],
            latency_ms=total_ms,
        )
        conv_id = await create_or_get_conversation(
            ctx,
            conversation_id=payload.conversation_id,
            first_query=payload.query,
        )
        await append_conversation_turn(
            ctx,
            conversation_id=conv_id,
            query_text=payload.query,
            answer_text=full_answer,
            citations=citations,
        )
        done_payload = {
            "answer": full_answer,
            "citations": citations,
            "conversation_id": str(conv_id),
            "trace": _build_trace(
                ctx, retrieval, embed_ms=embed_ms, llm_ms=llm_ms, total_ms=total_ms
            ),
        }
        yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations", tags=["rag"])
async def get_conversations(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, list[dict[str, object]]]:
    """List the caller's own saved chat conversations under RLS."""
    conversations = await list_conversations(ctx)
    return {"conversations": conversations}


@router.get("/conversations/{conversation_id}", tags=["rag"])
async def get_conversation(
    conversation_id: UUID,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Retrieve a saved conversation and its turns for the caller."""
    detail = await get_conversation_detail(ctx, conversation_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return {"conversation": detail}


@router.delete("/conversations/{conversation_id}", tags=["rag"])
async def remove_conversation(
    conversation_id: UUID,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Delete a saved conversation belonging to the caller."""
    deleted = await delete_conversation(ctx, conversation_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return {"deleted": True, "conversation_id": str(conversation_id)}


@router.get("/suggestions", tags=["rag"])
async def get_query_suggestions(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, list[str]]:
    """Return safe, non-leaking starter questions derived solely from accessible documents."""
    docs = await list_accessible_documents(ctx)
    if not docs:
        return {
            "suggestions": [
                "What documents do I currently have access to?",
                "How do I upload a document for my team?",
            ]
        }

    suggestions: list[str] = []
    for doc in docs[:3]:
        suggestions.append(f"Summarize the key points from {doc['title']}")
    if len(docs) > 1:
        depts = sorted({str(d.get("department", "General")) for d in docs})
        suggestions.append(f"What policies or guidelines apply to {depts[0]}?")
    return {"suggestions": suggestions[:4]}


@router.get("/audit", tags=["audit"])
async def get_audit_trail(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, list[dict[str, object]]]:
    """Return recent query audit logs scoped to the caller's organization via RLS."""
    logs = await list_audit_logs(ctx, limit=limit)
    return {"audit_logs": logs}
