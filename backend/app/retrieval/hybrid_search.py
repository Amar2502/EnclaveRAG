"""Hybrid search combining pgvector cosine similarity and tsvector FTS via RRF."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import UndefinedObject

from app.core.db import RLSContext, scoped_rls_transaction

_RRF_K = 60
_DEFAULT_MIN_VECTOR_SCORE = 0.40


@dataclass(frozen=True)
class RetrievedChunk:
    """Single RLS-authorized chunk ranked by Reciprocal Rank Fusion."""

    chunk_id: UUID
    document_id: UUID
    document_title: str
    department: str
    clearance_level: int
    classification_tag: str
    chunk_index: int
    content: str
    vector_score: float | None
    fts_score: float | None
    rrf_score: float

    def to_trace_dict(self) -> dict[str, Any]:
        """Serialize chunk with retrieval scores for the Security X-Ray trace."""
        return {
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "document_title": self.document_title,
            "department": self.department,
            "clearance_level": self.clearance_level,
            "classification_tag": self.classification_tag,
            "chunk_index": self.chunk_index,
            "snippet": self.content[:240] + ("..." if len(self.content) > 240 else ""),
            "vector_score": round(self.vector_score, 4) if self.vector_score is not None else None,
            "fts_score": round(self.fts_score, 4) if self.fts_score is not None else None,
            "rrf_score": round(self.rrf_score, 6),
        }


@dataclass(frozen=True)
class RetrievalResult:
    """Fused chunks plus retrieval diagnostics for observability."""

    chunks: list[RetrievedChunk]
    vector_candidates: int
    fts_candidates: int
    iterative_scan_enabled: bool
    retrieval_ms: int


async def _enable_iterative_scan(conn: AsyncConnection) -> bool:
    """Enable pgvector >= 0.8.0 iterative HNSW scan if supported, without aborting tx."""
    await conn.execute("SAVEPOINT sp_iterative_scan")
    try:
        await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
    except UndefinedObject:
        await conn.execute("ROLLBACK TO SAVEPOINT sp_iterative_scan")
        return False
    else:
        await conn.execute("RELEASE SAVEPOINT sp_iterative_scan")
        return True


def _fuse_rrf(
    dense_rows: list[tuple[Any, ...]],
    sparse_rows: list[tuple[Any, ...]],
    *,
    top_k: int,
    min_vector_score: float,
) -> list[RetrievedChunk]:
    """Combine dense vector and sparse FTS rankings with Reciprocal Rank Fusion."""
    merged: dict[UUID, dict[str, Any]] = {}

    for rank, row in enumerate(dense_rows, start=1):
        chunk_id: UUID = row[0]
        score = float(row[8])
        if score < min_vector_score:
            continue
        merged[chunk_id] = {
            "row": row,
            "vector_score": score,
            "fts_score": None,
            "rrf": 1.0 / (_RRF_K + rank),
        }

    for rank, row in enumerate(sparse_rows, start=1):
        chunk_id = row[0]
        fts_score = float(row[8])
        entry = merged.get(chunk_id)
        if entry is None:
            merged[chunk_id] = {
                "row": row,
                "vector_score": None,
                "fts_score": fts_score,
                "rrf": 1.0 / (_RRF_K + rank),
            }
        else:
            entry["fts_score"] = fts_score
            entry["rrf"] += 1.0 / (_RRF_K + rank)

    ranked = sorted(merged.values(), key=lambda item: item["rrf"], reverse=True)[:top_k]
    return [
        RetrievedChunk(
            chunk_id=item["row"][0],
            document_id=item["row"][1],
            document_title=item["row"][2],
            department=item["row"][3],
            clearance_level=item["row"][4],
            classification_tag=item["row"][5],
            chunk_index=item["row"][6],
            content=item["row"][7],
            vector_score=item["vector_score"],
            fts_score=item["fts_score"],
            rrf_score=item["rrf"],
        )
        for item in ranked
    ]


async def hybrid_rrf_search(
    ctx: RLSContext,
    *,
    query: str,
    query_embedding: list[float],
    top_k: int = 5,
    min_vector_score: float = _DEFAULT_MIN_VECTOR_SCORE,
) -> RetrievalResult:
    """Run RLS-scoped pgvector + tsvector search and fuse results via RRF."""
    start = time.perf_counter()
    candidate_limit = max(top_k * 3, 15)

    async with scoped_rls_transaction(ctx) as conn:
        iterative_scan = await _enable_iterative_scan(conn)

        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    c.id,
                    c.document_id,
                    d.title,
                    d.department,
                    d.clearance_level,
                    d.classification_tag,
                    c.chunk_index,
                    c.content,
                    (1.0 - (c.embedding <=> %s::vector))::float AS vector_score
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                ORDER BY c.embedding <=> %s::vector ASC
                LIMIT %s
                """,
                (query_embedding, query_embedding, candidate_limit),
            )
            dense_rows = await cur.fetchall()

            await cur.execute(
                """
                SELECT
                    c.id,
                    c.document_id,
                    d.title,
                    d.department,
                    d.clearance_level,
                    d.classification_tag,
                    c.chunk_index,
                    c.content,
                    ts_rank_cd(c.fts, websearch_to_tsquery('english', %s))::float AS fts_score
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.fts @@ websearch_to_tsquery('english', %s)
                ORDER BY fts_score DESC
                LIMIT %s
                """,
                (query, query, candidate_limit),
            )
            sparse_rows = await cur.fetchall()

    fused = _fuse_rrf(
        dense_rows,
        sparse_rows,
        top_k=top_k,
        min_vector_score=min_vector_score,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return RetrievalResult(
        chunks=fused,
        vector_candidates=len(dense_rows),
        fts_candidates=len(sparse_rows),
        iterative_scan_enabled=iterative_scan,
        retrieval_ms=elapsed_ms,
    )
