"""Offline retrieval evaluation helpers for RAG experiments."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.services.indexer import Indexer


@dataclass
class RetrievalExample:
    query: str
    relevant_chunk_ids: set[int]
    relevant_filenames: set[str]
    kb_id: Optional[int] = None
    user_id: Optional[int] = None


def load_retrieval_examples(path: str | Path) -> list[RetrievalExample]:
    examples: list[RetrievalExample] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            query = (row.get("query") or row.get("question") or "").strip()
            if not query:
                raise ValueError(f"Missing query at {path}:{line_no}")
            examples.append(
                RetrievalExample(
                    query=query,
                    relevant_chunk_ids={int(x) for x in row.get("relevant_chunk_ids", [])},
                    relevant_filenames={str(x) for x in row.get("relevant_filenames", [])},
                    kb_id=row.get("kb_id"),
                    user_id=row.get("user_id"),
                )
            )
    return examples


def _is_relevant(result: dict, example: RetrievalExample) -> bool:
    return (
        int(result.get("id", -1)) in example.relevant_chunk_ids
        or str(result.get("filename", "")) in example.relevant_filenames
    )


def evaluate_results(results: list[dict], example: RetrievalExample, k: int) -> dict:
    ranked = results[:k]
    hits = [1 if _is_relevant(r, example) else 0 for r in ranked]
    hit_rate = 1.0 if any(hits) else 0.0

    mrr = 0.0
    for idx, hit in enumerate(hits, start=1):
        if hit:
            mrr = 1.0 / idx
            break

    dcg = sum(hit / math.log2(idx + 1) for idx, hit in enumerate(hits, start=1))
    ideal_count = min(
        k,
        max(len(example.relevant_chunk_ids) + len(example.relevant_filenames), sum(hits), 1),
    )
    idcg = sum(1.0 / math.log2(idx + 1) for idx in range(1, ideal_count + 1))
    ndcg = dcg / idcg if idcg else 0.0

    return {"hit_rate": hit_rate, "mrr": mrr, "ndcg": ndcg}


def summarize_metrics(metrics: Iterable[dict]) -> dict:
    rows = list(metrics)
    if not rows:
        return {"count": 0, "hit_rate": 0.0, "mrr": 0.0, "ndcg": 0.0}
    return {
        "count": len(rows),
        "hit_rate": round(sum(r["hit_rate"] for r in rows) / len(rows), 4),
        "mrr": round(sum(r["mrr"] for r in rows) / len(rows), 4),
        "ndcg": round(sum(r["ndcg"] for r in rows) / len(rows), 4),
    }


def evaluate_retrieval(db: Session, examples: list[RetrievalExample], k: int = 5) -> dict:
    indexer = Indexer(db)
    per_query = []
    for example in examples:
        results = indexer.search_chunks(
            example.query,
            top_k=k,
            kb_id=example.kb_id,
            user_id=example.user_id,
        )
        metrics = evaluate_results(results, example, k)
        per_query.append(
            {
                "query": example.query,
                "metrics": metrics,
                "results": [
                    {
                        "id": r.get("id"),
                        "filename": r.get("filename"),
                        "chunk_index": r.get("chunk_index"),
                        "similarity": r.get("similarity"),
                        "retrieval_score": r.get("retrieval_score"),
                    }
                    for r in results[:k]
                ],
            }
        )
    return {"summary": summarize_metrics(row["metrics"] for row in per_query), "queries": per_query}
