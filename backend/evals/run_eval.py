"""Phase 4 RAG quality (Recall@5), security leak-rate, and latency benchmark runner.

Runs against the seeded PostgreSQL database (`db/seed/seed_data.py`).
Usage:
    python evals/run_eval.py                # Retrieval + leak-rate benchmark (Gemini embeddings)
    python evals/run_eval.py --mode full    # End-to-end Retrieval + Groq synthesis benchmark
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.db import RLSContext, close_db_pool, init_db_pool
from app.ingestion.embedder import embed_query
from app.ingestion.service import get_persona_by_email
from app.llm.synthesizer import NO_ACCESSIBLE_INFO_MESSAGE, synthesize_answer
from app.retrieval.hybrid_search import hybrid_rrf_search


def _percentile(values: list[float], pct: float) -> float:
    """Compute nearest-rank percentile in milliseconds."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return round(ordered[idx], 2)


async def run_benchmark(*, mode: str, top_k: int) -> dict[str, Any]:
    """Execute golden queries against seeded personas and summarize metrics."""
    golden_path = Path(__file__).parent / "golden_queries.json"
    cases: list[dict[str, Any]] = json.loads(golden_path.read_text(encoding="utf-8"))

    await init_db_pool()
    leaks = 0
    positive_cases = 0
    recall_hits = 0
    negative_cases = 0
    negative_pass = 0
    retrieval_latencies: list[float] = []
    e2e_latencies: list[float] = []
    results: list[dict[str, Any]] = []

    try:
        for case in cases:
            persona = await get_persona_by_email(case["persona_email"])
            if persona is None:
                raise RuntimeError(
                    f"Seeded persona '{case['persona_email']}' missing. Run db/seed/seed_data.py."
                )

            ctx = RLSContext(
                org_id=persona["org_id"],
                user_id=persona["user_id"],
                clearance_level=persona["clearance_level"],
                department=persona["department"],
            )

            t0 = time.perf_counter()
            query_vec = await embed_query(case["query"])
            retrieval = await hybrid_rrf_search(
                ctx,
                query=case["query"],
                query_embedding=query_vec,
                top_k=top_k,
            )
            retrieval_latencies.append(float(retrieval.retrieval_ms))

            retrieved_titles = {chunk.document_title for chunk in retrieval.chunks}
            forbidden = set(case["forbidden_doc_titles"])
            leaked_titles = sorted(retrieved_titles & forbidden)
            if leaked_titles:
                leaks += 1

            expected = set(case["expected_doc_titles"])
            recall_hit: bool | None = None
            if expected:
                positive_cases += 1
                recall_hit = expected.issubset(retrieved_titles)
                if recall_hit:
                    recall_hits += 1

            answer: str | None = None
            if mode == "full":
                answer = await synthesize_answer(case["query"], retrieval.chunks)
                if not expected:
                    negative_cases += 1
                    if answer.strip() == NO_ACCESSIBLE_INFO_MESSAGE:
                        negative_pass += 1

            e2e_ms = (time.perf_counter() - t0) * 1000.0
            e2e_latencies.append(e2e_ms)

            results.append(
                {
                    "id": case["id"],
                    "clearance": case["clearance_level"],
                    "retrieved_titles": sorted(retrieved_titles),
                    "leaked_titles": leaked_titles,
                    "recall_hit": recall_hit,
                    "retrieval_ms": retrieval.retrieval_ms,
                    "e2e_ms": round(e2e_ms, 1),
                    **({"answer": answer} if answer is not None else {}),
                }
            )
    finally:
        await close_db_pool()

    recall_at_k = round((recall_hits / positive_cases) * 100.0, 1) if positive_cases else 0.0
    summary: dict[str, Any] = {
        "mode": mode,
        "total_cases": len(cases),
        "security_leaks": leaks,
        "positive_cases": positive_cases,
        f"recall_at_{top_k}_pct": recall_at_k,
        "retrieval_p50_ms": _percentile(retrieval_latencies, 50),
        "retrieval_p95_ms": _percentile(retrieval_latencies, 95),
        "e2e_p50_ms": _percentile(e2e_latencies, 50),
        "e2e_p95_ms": _percentile(e2e_latencies, 95),
    }
    if mode == "full" and negative_cases:
        summary["neutral_fallback_pct"] = round((negative_pass / negative_cases) * 100.0, 1)

    return {"summary": summary, "cases": results}


def main() -> None:
    """CLI entrypoint for Phase 4 RAG benchmarks."""
    parser = argparse.ArgumentParser(description="Run EnclaveRAG Phase 4 evaluation suite.")
    parser.add_argument(
        "--mode",
        choices=("retrieval", "full"),
        default="retrieval",
        help="retrieval = DB + Gemini embeddings only; full = + Groq synthesis",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Top-K chunks for Recall@K")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report path")
    args = parser.parse_args()

    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            report = runner.run(run_benchmark(mode=args.mode, top_k=args.top_k))
    else:
        report = asyncio.run(run_benchmark(mode=args.mode, top_k=args.top_k))

    print(json.dumps(report["summary"], indent=2))
    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Saved detailed report to {args.output}")


if __name__ == "__main__":
    main()
