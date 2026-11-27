"""Phase 3 unit tests: Reciprocal Rank Fusion math and Groq synthesis guards."""

from typing import Self
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.llm.synthesizer import NO_ACCESSIBLE_INFO_MESSAGE, synthesize_answer
from app.retrieval.hybrid_search import RetrievedChunk, _fuse_rrf


def test_fuse_rrf_boosts_dual_matches_and_filters_low_vector_scores() -> None:
    """Chunks appearing in both dense and sparse results outrank single-list hits."""
    doc_id = uuid4()
    id_both = uuid4()
    id_dense_only = uuid4()
    id_low_noise = uuid4()

    dense_rows = [
        (id_dense_only, doc_id, "Doc A", "Eng", 2, "L2_INTERNAL", 0, "dense only", 0.90),
        (id_both, doc_id, "Doc A", "Eng", 2, "L2_INTERNAL", 1, "both hit", 0.85),
        (id_low_noise, doc_id, "Doc A", "Eng", 1, "L1_PUBLIC", 2, "noise", 0.20),
    ]
    sparse_rows = [
        (id_both, doc_id, "Doc A", "Eng", 2, "L2_INTERNAL", 1, "both hit", 0.75),
    ]

    fused = _fuse_rrf(dense_rows, sparse_rows, top_k=5, min_vector_score=0.40)
    fused_ids = [chunk.chunk_id for chunk in fused]

    assert id_low_noise not in fused_ids
    assert fused_ids == [id_both, id_dense_only]
    assert fused[0].vector_score == 0.85
    assert fused[0].fts_score == 0.75
    assert fused[1].fts_score is None


async def test_synthesize_answer_skips_llm_when_no_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty retrieval returns neutral fallback without calling Groq."""
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("Groq HTTP client must not be called when chunks are empty.")

    monkeypatch.setattr(httpx, "AsyncClient", fail_if_called)
    answer = await synthesize_answer("What is Project Helios?", [])

    assert answer == NO_ACCESSIBLE_INFO_MESSAGE
    assert called is False


async def test_synthesize_answer_sends_context_and_returns_groq_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Formats chunks into <context_chunks> and returns Groq chat completion text."""
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {"message": {"content": "Employees get 20 PTO days [Handbook | L1_PUBLIC]."}}
                ]
            }

    class FakeAsyncClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_title="Handbook",
        department="HR",
        clearance_level=1,
        classification_tag="L1_PUBLIC",
        chunk_index=0,
        content="Employees receive 20 PTO days per year.",
        vector_score=0.88,
        fts_score=0.50,
        rrf_score=0.032,
    )
    answer = await synthesize_answer("How many PTO days?", [chunk])

    assert "20 PTO days" in answer
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer test-groq-key",
    }
    messages = captured["json"]["messages"]  # type: ignore[index]
    assert "<context_chunks>" in messages[1]["content"]
    assert "Handbook | L1_PUBLIC" in messages[1]["content"]
