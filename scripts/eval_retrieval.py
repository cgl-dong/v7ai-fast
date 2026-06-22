"""Run offline retrieval evaluation.

Usage:
    python -m scripts.eval_retrieval --dataset data/eval/sample_questions.jsonl --top-k 5
"""
from __future__ import annotations

import argparse
import json

from app.core.database import SessionLocal
from app.services.eval import evaluate_retrieval, load_retrieval_examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval quality.")
    parser.add_argument("--dataset", default="data/eval/sample_questions.jsonl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Print full JSON output.")
    args = parser.parse_args()

    examples = load_retrieval_examples(args.dataset)
    db = SessionLocal()
    try:
        report = evaluate_retrieval(db, examples, k=args.top_k)
    finally:
        db.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    summary = report["summary"]
    print(f"queries={summary['count']}")
    print(f"HitRate@{args.top_k}={summary['hit_rate']}")
    print(f"MRR@{args.top_k}={summary['mrr']}")
    print(f"NDCG@{args.top_k}={summary['ndcg']}")


if __name__ == "__main__":
    main()
