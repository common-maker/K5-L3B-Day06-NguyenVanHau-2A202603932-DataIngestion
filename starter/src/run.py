"""End-to-end Day 06 data ingestion, vector indexing, and controlled retrieval benchmark."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_corpus_from_manifest
from .models import Chunk
from .store import PgVectorStore

STARTER_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = STARTER_DIR.parent
MANIFEST_PATH = PROJECT_ROOT / "data" / "manifest.json"
BENCHMARK_PATH = PROJECT_ROOT / "benchmark" / "questions.json"
RESULTS_DIR = STARTER_DIR / "results"

# 10 pre-registered positions selected a priori in benchmark/README.md.
COHERENCE_POSITIONS = [
    ("nist-ai-100-1", 6),
    ("nist-ai-100-1", 12),
    ("nist-ai-100-1", 22),
    ("nist-ai-100-1", 27),
    ("nist-ai-100-1", 34),
    ("nist-ai-600-1", 10),
    ("nist-ai-600-1", 18),
    ("nist-ai-600-1", 30),
    ("nist-ai-600-1", 36),
    ("nist-ai-600-1", 53),
]


def _chunk_stats(chunks: list[Chunk]) -> dict[str, Any]:
    lengths = sorted(len(c.text) for c in chunks)
    if not lengths:
        return {"count": 0}
    p95_idx = min(len(lengths) - 1, int(0.95 * (len(lengths) - 1)))
    return {
        "count": len(lengths),
        "total_chars": sum(lengths),
        "min_chars": lengths[0],
        "median_chars": statistics.median(lengths),
        "mean_chars": round(statistics.mean(lengths), 1),
        "p95_chars": lengths[p95_idx],
        "max_chars": lengths[-1],
    }


def _verify_idempotency(
    store: PgVectorStore,
    b_chunks: list[Chunk],
    b_vectors: list[list[float]],
) -> dict[str, Any]:
    """Verify duplicate-free re-ingest and stale-chunk deletion on document change."""
    before_b = store.count_chunks("B")
    doc1_pairs = [
        (c, v) for c, v in zip(b_chunks, b_vectors) if c.document_id == "nist-ai-100-1"
    ]
    store.upsert(
        "B",
        [c for c, _ in doc1_pairs],
        [v for _, v in doc1_pairs],
        prune_missing_documents=False,
    )
    after_b = store.count_chunks("B")

    # Isolated stale-chunk cleanup verification using two chunks -> one chunk.
    probe_strategy = "_idempotency_probe"
    store.delete_strategy(probe_strategy)
    c0, v0 = doc1_pairs[0]
    c1, v1 = doc1_pairs[1]
    store.upsert(probe_strategy, [c0, c1], [v0, v1], prune_missing_documents=True)
    probe_initial = store.count_chunks(probe_strategy)
    store.upsert(probe_strategy, [c0], [v0], prune_missing_documents=True)
    probe_after_shrink = store.count_chunks(probe_strategy)
    store.delete_strategy(probe_strategy)

    if before_b != after_b or probe_initial != 2 or probe_after_shrink != 1:
        raise RuntimeError(
            f"Idempotency check failed: B {before_b}->{after_b}, "
            f"probe {probe_initial}->{probe_after_shrink}"
        )

    return {
        "reingest_strategy": "B",
        "reingest_doc_id": "nist-ai-100-1",
        "count_before": before_b,
        "count_after": after_b,
        "stale_cleanup_probe_initial": probe_initial,
        "stale_cleanup_probe_after_shrink": probe_after_shrink,
        "passed": True,
    }


def _export_coherence_samples(
    chunks_a: list[Chunk],
    chunks_b: list[Chunk],
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for doc_id, page_num in COHERENCE_POSITIONS:
        a_matches = [
            {
                "chunk_id": c.chunk_id,
                "section": c.metadata.get("section"),
                "char_len": len(c.text),
                "text": c.text,
            }
            for c in chunks_a
            if c.document_id == doc_id and c.page == page_num
        ]
        b_matches = [
            {
                "chunk_id": c.chunk_id,
                "section": c.metadata.get("section"),
                "char_len": len(c.text),
                "text": c.text,
            }
            for c in chunks_b
            if c.document_id == doc_id and c.page == page_num
        ]
        samples.append(
            {
                "document_id": doc_id,
                "page": page_num,
                "strategy_A_chunks": a_matches,
                "strategy_BC_chunks": b_matches,
            }
        )
    return samples


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Day 06 Data Ingestion & Benchmark Pipeline")
    parser.add_argument(
        "--split",
        choices=["dev", "test", "all"],
        default="all",
        help="Benchmark split to evaluate (default: all).",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip re-embedding and reuse already stored chunks in pgvector.",
    )
    args = parser.parse_args(argv)

    load_dotenv(STARTER_DIR / ".env")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL missing in starter/.env")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_started = datetime.now(timezone.utc).isoformat()

    # 1. Load & validate corpus (>= 30 valid content pages).
    t_ingest_start = time.perf_counter()
    pages, ingestion_errors = load_corpus_from_manifest(MANIFEST_PATH, PROJECT_ROOT)
    ingest_parse_seconds = time.perf_counter() - t_ingest_start
    if len(pages) < 30:
        raise RuntimeError(f"Corpus has {len(pages)} valid pages; minimum 30 required.")

    (RESULTS_DIR / "ingestion_log.json").write_text(
        json.dumps(
            {
                "valid_pages_loaded": len(pages),
                "parse_seconds": round(ingest_parse_seconds, 4),
                "errors": ingestion_errors,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 2. Load benchmark & validate split filter.
    all_questions = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    if args.split == "all":
        eval_questions = all_questions
    else:
        eval_questions = [q for q in all_questions if q["split"] == args.split]

    # 3. Initialize real embedder & persistent vector store.
    embedder = MyEmbedder(model_name="text-embedding-3-small", batch_size=64)
    store = PgVectorStore(database_url=database_url, dimensions=embedder.dimensions)
    store.create_schema()

    # 4. Build chunks for A (fixed_size) and B/C (by_paragraph).
    chunks_a: list[Chunk] = []
    chunks_b: list[Chunk] = []
    for p in pages:
        chunks_a.extend(fixed_size(p, size=500, overlap=50))
        chunks_b.extend(by_paragraph(p, max_size=1000))

    chunk_stats = {
        "A": {"chunking": "fixed_size(500, overlap=50)", **_chunk_stats(chunks_a)},
        "B": {"chunking": "by_paragraph(max_size=1000)", **_chunk_stats(chunks_b)},
        "C": {"chunking": "by_paragraph(max_size=1000, shared with B)", **_chunk_stats(chunks_b)},
    }
    (RESULTS_DIR / "chunk_stats.json").write_text(
        json.dumps(chunk_stats, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (RESULTS_DIR / "coherence_samples.json").write_text(
        json.dumps(_export_coherence_samples(chunks_a, chunks_b), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    strategy_ingest_metrics: dict[str, Any] = {}
    idempotency_report: dict[str, Any] | None = None

    if not args.skip_ingest:
        # Strategy A ingest
        tok_before = embedder.total_prompt_tokens
        cost_before = embedder.estimated_cost_usd
        t0 = time.perf_counter()
        vecs_a = embedder.embed_documents([c.text for c in chunks_a])
        t_embed_a = time.perf_counter() - t0
        t1 = time.perf_counter()
        store.upsert("A", chunks_a, vecs_a, prune_missing_documents=True)
        t_db_a = time.perf_counter() - t1
        strategy_ingest_metrics["A"] = {
            "chunk_count": len(chunks_a),
            "prompt_tokens": embedder.total_prompt_tokens - tok_before,
            "embed_seconds": round(t_embed_a, 3),
            "db_upsert_seconds": round(t_db_a, 3),
            "total_ingest_seconds": round(t_embed_a + t_db_a, 3),
            "cost_usd": round(embedder.estimated_cost_usd - cost_before, 6),
        }

        # Strategy B ingest
        tok_before = embedder.total_prompt_tokens
        cost_before = embedder.estimated_cost_usd
        t0 = time.perf_counter()
        vecs_b = embedder.embed_documents([c.text for c in chunks_b])
        t_embed_b = time.perf_counter() - t0
        t1 = time.perf_counter()
        store.upsert("B", chunks_b, vecs_b, prune_missing_documents=True)
        t_db_b = time.perf_counter() - t1
        strategy_ingest_metrics["B"] = {
            "chunk_count": len(chunks_b),
            "prompt_tokens": embedder.total_prompt_tokens - tok_before,
            "embed_seconds": round(t_embed_b, 3),
            "db_upsert_seconds": round(t_db_b, 3),
            "total_ingest_seconds": round(t_embed_b + t_db_b, 3),
            "cost_usd": round(embedder.estimated_cost_usd - cost_before, 6),
        }

        # Strategy C stores identical chunks & vectors to B (zero additional embedding cost).
        t1 = time.perf_counter()
        store.upsert("C", chunks_b, vecs_b, prune_missing_documents=True)
        t_db_c = time.perf_counter() - t1
        strategy_ingest_metrics["C"] = {
            "chunk_count": len(chunks_b),
            "prompt_tokens": 0,
            "embed_seconds": 0.0,
            "db_upsert_seconds": round(t_db_c, 3),
            "total_ingest_seconds": round(t_db_c, 3),
            "cost_usd": 0.0,
            "note": "Reuses Strategy B embeddings; adds SQL metadata filter at query time.",
        }

        idempotency_report = _verify_idempotency(store, chunks_b, vecs_b)

    # 5. Embed all queries in the requested split once (shared query vectors across A/B/C).
    tok_q_before = embedder.total_prompt_tokens
    cost_q_before = embedder.estimated_cost_usd
    t_q_embed_start = time.perf_counter()
    query_vectors = {
        q["id"]: embedder.embed_query(q["question"]) for q in eval_questions
    }
    query_embed_seconds = time.perf_counter() - t_q_embed_start
    query_embed_tokens = embedder.total_prompt_tokens - tok_q_before
    query_embed_cost = embedder.estimated_cost_usd - cost_q_before

    # 6. Run retrieval for A, B, and C.
    traces: list[dict[str, Any]] = []
    search_seconds: dict[str, float] = {}
    for strategy in ["A", "B", "C"]:
        t_s = time.perf_counter()
        for q in eval_questions:
            active_filter = q.get("filter") if strategy == "C" else None
            hits = store.search(
                strategy=strategy,
                query_vector=query_vectors[q["id"]],
                top_k=3,
                filters=active_filter,
            )
            traces.append(
                evaluate_query(
                    question=q,
                    hits=hits,
                    strategy=strategy,
                    filter_applied=active_filter,
                )
            )
        search_seconds[strategy] = round(time.perf_counter() - t_s, 4)

    summary = summarize(traces)
    split_tag = args.split

    (RESULTS_DIR / f"traces_{split_tag}.json").write_text(
        json.dumps(traces, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (RESULTS_DIR / f"summary_{split_tag}.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if args.split in ("test", "all"):
        test_traces = [t for t in traces if t["split"] == "test"]
        (RESULTS_DIR / "test_audit_extract.json").write_text(
            json.dumps(test_traces, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    run_meta = {
        "run_started_utc": run_started,
        "split": args.split,
        "skip_ingest": args.skip_ingest,
        "embedding_model": embedder.model_name,
        "embedding_dimensions": embedder.dimensions,
        "vector_store": "PostgreSQL 16.16 + pgvector 0.8.7 (exact cosine distance <=>)",
        "total_prompt_tokens": embedder.total_prompt_tokens,
        "total_cost_usd": round(embedder.estimated_cost_usd, 6),
        "query_embed_tokens": query_embed_tokens,
        "query_embed_seconds": round(query_embed_seconds, 3),
        "query_embed_cost_usd": round(query_embed_cost, 6),
        "search_seconds_by_strategy": search_seconds,
        "strategy_ingest_metrics": strategy_ingest_metrics,
        "idempotency_verification": idempotency_report,
    }
    (RESULTS_DIR / f"run_metadata_{split_tag}.json").write_text(
        json.dumps(run_meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"=== Run Summary (split={args.split}) ===")
    for key, stats in summary.items():
        fc = stats["filter_compliance"]
        fc_str = fc["ratio"] if fc else "N/A"
        print(
            f"  {key:10s} | Hit@1={stats['hit_at_1_ratio']} ({stats['hit_at_1_pct']}%) | "
            f"Evidence Hit@3={stats['evidence_hit_at_3_ratio']} ({stats['evidence_hit_at_3_pct']}%) | "
            f"PageHit@3={stats['source_page_hit_at_3']}/{stats['total']} | "
            f"SplitEv={stats['evidence_split_across_top3']} | Filter={fc_str}"
        )


if __name__ == "__main__":
    main()
