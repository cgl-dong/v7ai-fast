from types import SimpleNamespace

from app.services.eval import RetrievalExample, evaluate_results, summarize_metrics
from app.services.indexer import Indexer, _rrf_merge


class FakeDB:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((str(sql), params))
        return []


def test_dense_search_filters_by_kb_and_user(monkeypatch):
    import app.services.indexer as indexer_module

    monkeypatch.setattr(indexer_module, "embed_query", lambda _: [0.1, 0.2, 0.3])
    fake_db = FakeDB()
    indexer = Indexer.__new__(Indexer)
    indexer.db = fake_db

    indexer._dense_search("annual leave", top_k=3, kb_id=7, user_id=42)

    sql, params = fake_db.calls[0]
    assert "kf.kb_id = :kb_id" in sql
    assert "(kf.user_id = :user_id OR kf.user_id IS NULL)" in sql
    assert params["kb_id"] == 7
    assert params["user_id"] == 42
    assert params["limit"] == 3


def test_rrf_merge_deduplicates_and_ranks_shared_hits_first():
    dense = [
        {"id": 1, "similarity": 0.9, "filename": "a.pdf"},
        {"id": 2, "similarity": 0.8, "filename": "b.pdf"},
    ]
    bm25 = [
        {"id": 2, "similarity": 3.0, "filename": "b.pdf"},
        {"id": 3, "similarity": 2.0, "filename": "c.pdf"},
    ]

    merged = _rrf_merge([dense, bm25], top_k=3, rrf_k=60)

    assert [row["id"] for row in merged] == [2, 1, 3]
    assert merged[0]["retrieval_score"] > merged[1]["retrieval_score"]


def test_retrieval_metrics_hit_mrr_ndcg():
    example = RetrievalExample(
        query="policy",
        relevant_chunk_ids={3},
        relevant_filenames=set(),
    )
    results = [
        {"id": 1, "filename": "a.pdf"},
        {"id": 3, "filename": "b.pdf"},
        {"id": 5, "filename": "c.pdf"},
    ]

    metrics = evaluate_results(results, example, k=3)

    assert metrics["hit_rate"] == 1.0
    assert metrics["mrr"] == 0.5
    assert 0 < metrics["ndcg"] < 1


def test_summarize_metrics_empty_and_average():
    assert summarize_metrics([])["count"] == 0
    summary = summarize_metrics([
        {"hit_rate": 1.0, "mrr": 1.0, "ndcg": 1.0},
        {"hit_rate": 0.0, "mrr": 0.0, "ndcg": 0.5},
    ])
    assert summary == {"count": 2, "hit_rate": 0.5, "mrr": 0.5, "ndcg": 0.75}
