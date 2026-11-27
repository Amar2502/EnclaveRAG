"""Async Gemini embedding client using httpx (no extra SDK dependency required)."""

from __future__ import annotations

import math

import httpx

from app.core.config import settings

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_BATCH_SIZE = 50


def _l2_normalize(vector: list[float]) -> list[float]:
    """Normalize truncated Matryoshka vectors to unit length for cosine similarity."""
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


async def _batch_embed(
    texts: list[str],
    *,
    task_type: str,
) -> list[list[float]]:
    """Call Gemini batchEmbedContents in batches and return normalized embeddings."""
    if not texts:
        return []
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured in .env")

    model_name = settings.gemini_embedding_model
    model_path = model_name if model_name.startswith("models/") else f"models/{model_name}"
    url = f"{_GEMINI_API_BASE}/{model_path}:batchEmbedContents"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": settings.gemini_api_key,
    }

    embeddings: list[list[float]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for offset in range(0, len(texts), _BATCH_SIZE):
            batch = texts[offset : offset + _BATCH_SIZE]
            payload = {
                "requests": [
                    {
                        "model": model_path,
                        "content": {"parts": [{"text": text}]},
                        "taskType": task_type,
                        "outputDimensionality": settings.embedding_dimension,
                    }
                    for text in batch
                ]
            }
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            for item in data["embeddings"]:
                embeddings.append(_l2_normalize(item["values"]))

    return embeddings


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Generate RETRIEVAL_DOCUMENT embeddings for document chunks."""
    return await _batch_embed(texts, task_type="RETRIEVAL_DOCUMENT")


async def embed_query(query: str) -> list[float]:
    """Generate a single RETRIEVAL_QUERY embedding for search."""
    vectors = await _batch_embed([query], task_type="RETRIEVAL_QUERY")
    return vectors[0]
