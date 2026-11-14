"""Evaluate top-k retrieval traces against gold evidence without fabricating manual labels."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _gold_candidates(question: dict[str, Any]) -> list[tuple[str, int, str]]:
    candidates = [
        (
            str(question["gold_source_id"]),
            int(question["gold_page"]),
            _collapse_ws(str(question["evidence_quote"])),
        )
    ]
    for alt in question.get("acceptable_gold", []) or []:
        candidates.append(
            (
                str(alt["source_id"]),
                int(alt["page"]),
                _collapse_ws(str(alt["evidence_quote"])),
            )
        )
    return candidates


def _matches_filter(hit: dict[str, Any], filters: dict[str, Any]) -> bool:
    meta = hit.get("metadata", {})
    for key, expected in filters.items():
        if key == "document_id":
            actual = hit.get("document_id")
        else:
            actual = meta.get(key)
        if actual != expected:
            return False
    return True


def evaluate_query(
    question: dict[str, Any],
    hits: list[dict[str, Any]],
    strategy: str = "",
    filter_applied: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check source/page and full gold evidence presence in top-1 and top-3 hits."""
    candidates = _gold_candidates(question)
    matched_rank: int | None = None
    source_page_ranks: list[int] = []

    annotated_hits: list[dict[str, Any]] = []
    for rank, hit in enumerate(hits, start=1):
        hit_doc = str(hit["document_id"])
        hit_page = int(hit["page"])
        hit_norm_text = _collapse_ws(str(hit["text"]))

        page_matched = any(doc == hit_doc and pg == hit_page for doc, pg, _ in candidates)
        if page_matched:
            source_page_ranks.append(rank)

        evidence_matched = any(
            doc == hit_doc and pg == hit_page and quote in hit_norm_text
            for doc, pg, quote in candidates
        )
        if evidence_matched and matched_rank is None:
            matched_rank = rank

        annotated_hits.append(
            {
                "rank": rank,
                "chunk_id": hit["chunk_id"],
                "document_id": hit_doc,
                "source": hit["source"],
                "page": hit_page,
                "score": hit["score"],
                "cosine_distance": hit.get("cosine_distance"),
                "metadata": hit.get("metadata", {}),
                "matches_gold_page": page_matched,
                "matches_gold_evidence": evidence_matched,
                "text": hit["text"],
            }
        )

    hit_at_1 = matched_rank == 1
    hit_at_3 = matched_rank is not None and matched_rank <= 3

    # Diagnostic only (does not alter primary Evidence Hit@3): check if splitting severed evidence.
    split_across_top3 = False
    if not hit_at_3 and source_page_ranks:
        for doc, pg, quote in candidates:
            combined = _collapse_ws(
                " ".join(
                    str(h["text"])
                    for h in hits
                    if str(h["document_id"]) == doc and int(h["page"]) == pg
                )
            )
            if quote in combined:
                split_across_top3 = True
                break

    filter_compliant: bool | None = None
    if filter_applied:
        filter_compliant = len(hits) > 0 and all(_matches_filter(h, filter_applied) for h in hits)

    return {
        "strategy": strategy,
        "question_id": question["id"],
        "split": question["split"],
        "type": question["type"],
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "gold_source_id": question["gold_source_id"],
        "gold_page": int(question["gold_page"]),
        "evidence_quote": question["evidence_quote"],
        "acceptable_gold": question.get("acceptable_gold", []),
        "question_filter": question.get("filter"),
        "filter_applied": filter_applied,
        "hit_at_1": hit_at_1,
        "evidence_hit_at_3": hit_at_3,
        "matched_gold_rank": matched_rank,
        "source_page_hit_at_3": bool(source_page_ranks),
        "evidence_split_across_top3": split_across_top3,
        "filter_compliant": filter_compliant,
        "hits": annotated_hits,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1, Evidence Hit@3, and filter compliance by (strategy, split)."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        grouped[(str(trace["strategy"]), str(trace["split"]))].append(trace)

    summary: dict[str, Any] = {}
    for (strategy, split), items in sorted(grouped.items()):
        total = len(items)
        hit1 = sum(1 for item in items if item["hit_at_1"])
        hit3 = sum(1 for item in items if item["evidence_hit_at_3"])
        page_hit3 = sum(1 for item in items if item["source_page_hit_at_3"])
        split_ev = sum(1 for item in items if item["evidence_split_across_top3"])

        filtered = [item for item in items if item["filter_applied"]]
        if filtered:
            compliant = sum(1 for item in filtered if item["filter_compliant"])
            filter_stats: dict[str, Any] | None = {
                "compliant": compliant,
                "total_filtered": len(filtered),
                "ratio": f"{compliant}/{len(filtered)}",
            }
        else:
            filter_stats = None

        summary[f"{strategy}:{split}"] = {
            "strategy": strategy,
            "split": split,
            "total": total,
            "hit_at_1": hit1,
            "hit_at_1_ratio": f"{hit1}/{total}",
            "hit_at_1_pct": round(100.0 * hit1 / total, 1) if total else 0.0,
            "evidence_hit_at_3": hit3,
            "evidence_hit_at_3_ratio": f"{hit3}/{total}",
            "evidence_hit_at_3_pct": round(100.0 * hit3 / total, 1) if total else 0.0,
            "source_page_hit_at_3": page_hit3,
            "evidence_split_across_top3": split_ev,
            "filter_compliance": filter_stats,
        }

    return summary
