"""Rating service — multi-dimensional quality scoring for traces and observations.

Supports:
- Trace-level scoring: overall quality assessment per conversation turn
- Observation-level scoring: per-node evaluation (classify/retrieve/generate)
- Aggregated analytics: trend analysis, per-dimension averages
"""

import json
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import TraceRating

# Dimension definitions per node type — matching README spec
NODE_DIMENSIONS = {
    "classify": ["accuracy", "relevance", "completeness"],
    "retrieve": ["hit_rate", "diversity"],
    "generate_with_docs": ["accuracy", "fluency", "usefulness"],
    "generate_no_docs": ["accuracy", "fluency", "usefulness"],
    "generate": ["accuracy", "fluency", "usefulness"],
    "fallback": ["appropriateness", "helpfulness"],
    "__trace__": ["overall_quality", "response_speed", "helpfulness"],
}
DIMENSION_LABELS = {
    "accuracy": "准确性",
    "relevance": "相关性",
    "completeness": "完整性",
    "hit_rate": "命中率",
    "diversity": "多样性",
    "fluency": "流畅度",
    "usefulness": "有用性",
    "appropriateness": "恰当性",
    "helpfulness": "帮助程度",
    "overall_quality": "综合质量",
    "response_speed": "响应速度",
}


def compute_overall(dimensions: dict) -> float:
    """Compute weighted average from dimension scores (1-5 scale)."""
    if not dimensions:
        return 0.0
    return round(sum(dimensions.values()) / len(dimensions), 1)


def get_dimensions_for(target_type: str, node_name: str = None) -> list[str]:
    """Return applicable dimension keys for the given target."""
    if target_type == "trace":
        return NODE_DIMENSIONS["__trace__"]
    if node_name and node_name in NODE_DIMENSIONS:
        return NODE_DIMENSIONS[node_name]
    return NODE_DIMENSIONS.get("__trace__", [])


class RatingService:
    """Creates, queries, and aggregates trace/observation ratings."""

    def __init__(self, db: Session):
        self.db = db

    def rate(self, target_type: str, target_id: str, dimension_scores: dict,
             session_id: str = "", node_name: str = "", scorer: str = "",
             comment: str = "", rater_type: str = "human", judge_model: str = "",
             dimension_reasons: dict = None) -> TraceRating:
        """Create or update a rating.

        If a rating for the same (target_type, target_id, scorer) exists, update it.
        """
        # Look up existing
        existing = (
            self.db.query(TraceRating)
            .filter(
                TraceRating.target_type == target_type,
                TraceRating.target_id == target_id,
                TraceRating.scorer == scorer,
            )
            .first()
        )

        overall = compute_overall(dimension_scores)
        dims_json = json.dumps(dimension_scores, ensure_ascii=False)
        reasons_json = json.dumps(dimension_reasons, ensure_ascii=False) if dimension_reasons else None

        if existing:
            existing.dimension_scores = dims_json
            existing.overall_score = overall
            existing.comment = comment or existing.comment
            existing.rater_type = rater_type
            if reasons_json:
                existing.dimension_reasons = reasons_json
            self.db.commit()
            self.db.refresh(existing)
            return existing

        record = TraceRating(
            target_type=target_type,
            target_id=target_id,
            session_id=session_id or "",
            node_name=node_name or "",
            rater_type=rater_type,
            scorer=scorer or "anonymous",
            judge_model=judge_model or "",
            dimension_scores=dims_json,
            dimension_reasons=reasons_json,
            overall_score=overall,
            comment=comment or "",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def query_ratings(
        self,
        target_type: str = None,
        target_id: str = None,
        session_id: str = None,
        limit: int = 50,
    ) -> list:
        """Query ratings with optional filters."""
        q = self.db.query(TraceRating)
        if target_type:
            q = q.filter(TraceRating.target_type == target_type)
        if target_id:
            q = q.filter(TraceRating.target_id == target_id)
        if session_id:
            q = q.filter(TraceRating.session_id == session_id)
        q = q.order_by(TraceRating.created_at.desc()).limit(limit)
        return [_rating_to_dict(r) for r in q]

    def stats(self, target_type: str = None, node_name: str = None, rater_type: str = None) -> dict:
        """Aggregated rating statistics with optional rater_type filter."""
        q = self.db.query(TraceRating)
        if target_type:
            q = q.filter(TraceRating.target_type == target_type)
        if node_name:
            q = q.filter(TraceRating.node_name == node_name)
        if rater_type:
            q = q.filter(TraceRating.rater_type == rater_type)

        records = q.all()
        if not records:
            return {"total": 0, "avg_overall": 0, "by_dimension": {}, "by_node": {}}

        avg_overall = round(
            sum(r.overall_score for r in records) / len(records), 1
        )

        # Aggregate per-dimension averages
        dim_sums: dict[str, float] = {}
        dim_counts: dict[str, int] = {}
        for r in records:
            try:
                dims = json.loads(r.dimension_scores) if isinstance(r.dimension_scores, str) else r.dimension_scores
            except (json.JSONDecodeError, TypeError):
                continue
            for k, v in dims.items():
                dim_sums[k] = dim_sums.get(k, 0) + v
                dim_counts[k] = dim_counts.get(k, 0) + 1

        by_dimension = {}
        for k in dim_sums:
            by_dimension[k] = {
                "label": DIMENSION_LABELS.get(k, k),
                "avg": round(dim_sums[k] / dim_counts[k], 1),
                "count": dim_counts[k],
            }

        # Per-node breakdown
        by_node = {}
        node_groups = {}
        for r in records:
            node = r.node_name or "trace"
            node_groups.setdefault(node, []).append(r.overall_score)

        for node, scores in node_groups.items():
            by_node[node] = {
                "count": len(scores),
                "avg_overall": round(sum(scores) / len(scores), 1),
            }

        return {
            "total": len(records),
            "avg_overall": avg_overall,
            "by_dimension": by_dimension,
            "by_node": by_node,
        }

    def dimensions_for_target(self, target_type: str, node_name: str = None) -> list[dict]:
        """Return dimension definitions for a target (used by frontend to render rating form)."""
        keys = get_dimensions_for(target_type, node_name)
        return [{"key": k, "label": DIMENSION_LABELS.get(k, k), "max": 5} for k in keys]


def _rating_to_dict(r: TraceRating) -> dict:
    try:
        dims = json.loads(r.dimension_scores) if isinstance(r.dimension_scores, str) else r.dimension_scores
    except (json.JSONDecodeError, TypeError):
        dims = {}
    try:
        reasons = json.loads(r.dimension_reasons) if r.dimension_reasons and isinstance(r.dimension_reasons, str) else (r.dimension_reasons or {})
    except (json.JSONDecodeError, TypeError):
        reasons = {}

    return {
        "id": r.id,
        "target_type": r.target_type,
        "target_id": r.target_id,
        "session_id": r.session_id,
        "node_name": r.node_name,
        "rater_type": r.rater_type or "human",
        "scorer": r.scorer,
        "judge_model": r.judge_model or "",
        "dimension_scores": dims,
        "dimension_reasons": reasons,
        "overall_score": r.overall_score,
        "comment": r.comment,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }
