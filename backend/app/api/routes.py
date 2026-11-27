"""Phase 1-3 API routes (auth, ingestion, hybrid RRF query, citation proxy, audit trail)."""

from __future__ import annotations

import time
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.core.db import RLSContext, scoped_rls_transaction
from app.core.security import create_access_token, get_current_rls_context
from app.ingestion.chunker import extract_text_from_upload
from app.ingestion.embedder import embed_query
from app.ingestion.service import (
    ClearanceViolationError,
    get_persona_by_email,
    ingest_document,
    list_accessible_documents,
    list_demo_personas,
    reclassify_document,
)
from app.llm.synthesizer import NO_ACCESSIBLE_INFO_MESSAGE, synthesize_answer
from app.retrieval.audit import (
    get_accessible_document_detail,
    list_audit_logs,
    log_query_audit,
)
from app.retrieval.hybrid_search import hybrid_rrf_search

router = APIRouter()


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
    """Payload for O(1) document clearance updates."""

    clearance_level: int = Field(ge=1, le=4)


class QueryRequest(BaseModel):
    """Payload for RLS-scoped hybrid RAG queries."""

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


@router.get("/personas", tags=["auth"])
async def get_personas() -> dict[str, list[dict[str, object]]]:
    """List seeded demo personas across organizations."""
    personas = await list_demo_personas()
    return {"personas": personas}


@router.post("/auth/persona-token", tags=["auth"])
async def issue_persona_token(payload: PersonaTokenRequest) -> dict[str, object]:
    """Issue a signed JWT for a seeded demo persona."""
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
    )
    token = create_access_token(ctx)
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
            "current_setting('app.user_id', true)"
        )
        row = await cur.fetchone()

    db_org_id, db_clearance, db_user_id = row if row else (None, None, None)
    return {
        "jwt_claims": {
            "user_id": str(ctx.user_id),
            "org_id": str(ctx.org_id),
            "clearance_level": ctx.clearance_level,
            "department": ctx.department,
        },
        "postgres_session": {
            "app.org_id": db_org_id,
            "app.clearance_level": int(db_clearance) if db_clearance else None,
            "app.user_id": db_user_id,
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
        )
        return {"document": record.to_dict()}
    except ClearanceViolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
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
) -> dict[str, object]:
    """Ingest an uploaded .txt, .md, or .pdf document under RLS."""
    raw_bytes = await file.read()
    filename = file.filename or "uploaded.txt"
    try:
        extracted = extract_text_from_upload(filename, raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return await _run_ingest(
        ctx,
        title=title or filename,
        department=department,
        clearance_level=clearance_level,
        content=extracted,
        source_uri=f"upload://{filename}",
    )


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
        )
    except ClearanceViolationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    return {"document": updated.to_dict()}


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


@router.post("/query", tags=["rag"])
async def query_knowledge_base(
    payload: QueryRequest,
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
) -> dict[str, object]:
    """Execute RLS-scoped hybrid retrieval, Groq synthesis, and audit logging."""
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

    llm_start = time.perf_counter()
    try:
        answer = await synthesize_answer(payload.query, retrieval.chunks)
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Chat synthesis service error: {exc}",
        ) from exc
    llm_ms = int((time.perf_counter() - llm_start) * 1000)

    total_ms = int((time.perf_counter() - total_start) * 1000)

    citations: list[dict[str, object]] = []
    if answer != NO_ACCESSIBLE_INFO_MESSAGE:
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

    await log_query_audit(
        ctx,
        query_text=payload.query,
        retrieved_doc_ids=[chunk.document_id for chunk in retrieval.chunks],
        latency_ms=total_ms,
    )

    return {
        "answer": answer,
        "citations": citations,
        "trace": {
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
        },
    }


@router.get("/audit", tags=["audit"])
async def get_audit_trail(
    ctx: Annotated[RLSContext, Depends(get_current_rls_context)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, list[dict[str, object]]]:
    """Return recent query audit logs scoped to the caller's organization via RLS."""
    logs = await list_audit_logs(ctx, limit=limit)
    return {"audit_logs": logs}
