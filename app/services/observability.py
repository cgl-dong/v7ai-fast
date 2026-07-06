"""Observability service — structured tracing for AI agent workflows.

Provides per-node latency, token estimation, error tracking for:
- Agent nodes (classify, retrieve, generate)
- LLM API calls
- Fallback flows

Data is persisted to the ai_traces table for Admin panel visualization.
"""
import json
import logging
import time
import uuid
import functools
from typing import Optional
from sqlalchemy.orm import Session

from app.core.database import AITrace

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Rough token count estimation (中文 ~1.5 char/token, 英文 ~4 char/token)."""
    if not text:
        return 0
    # Simple heuristic: 4 chars per token for mixed CN/EN text
    return max(1, len(text) // 2)


class Tracer:
    """Traces AI agent execution steps and persists to DB."""

    def __init__(self, db: Session):
        self.db = db

    def trace(
        self,
        node_name: str,
        session_id: str = "",
        trace_type: str = "agent_node",
        model_name: str = "",
        metadata: dict = None,
    ):
        """Context manager for tracing a single execution step.

        Usage:
            with tracer.trace("classify", session_id="abc123") as ctx:
                ctx.input = "user question"
                result = do_work()
                ctx.output = result
        """
        return _TraceContext(
            db=self.db,
            node_name=node_name,
            session_id=session_id,
            trace_type=trace_type,
            model_name=model_name,
            metadata=metadata or {},
        )

    def query_traces(
        self,
        session_id: str = None,
        node_name: str = None,
        status: str = None,
        limit: int = 50,
    ) -> list:
        """Query traces with optional filters."""
        q = self.db.query(AITrace)
        if session_id:
            q = q.filter(AITrace.session_id == session_id)
        if node_name:
            q = q.filter(AITrace.node_name == node_name)
        if status:
            q = q.filter(AITrace.status == status)
        q = q.order_by(AITrace.created_at.desc()).limit(limit)
        return [
            {
                "id": t.id,
                "trace_id": t.trace_id,
                "session_id": t.session_id,
                "node_name": t.node_name,
                "trace_type": t.trace_type,
                "model_name": t.model_name,
                "input_summary": t.input_summary,
                "output_summary": t.output_summary,
                "status": t.status,
                "latency_ms": t.latency_ms,
                "token_count": t.token_count,
                "error_msg": t.error_msg,
                "created_at": t.created_at.isoformat() if t.created_at else "",
            }
            for t in q
        ]

    def stats(self) -> dict:
        """Aggregated trace statistics."""
        total = self.db.query(AITrace).count()
        success = self.db.query(AITrace).filter(AITrace.status == "success").count()
        error = self.db.query(AITrace).filter(AITrace.status == "error").count()

        avg_latency = 0
        if total > 0:
            from sqlalchemy import func
            avg_latency = round(
                self.db.query(func.avg(AITrace.latency_ms)).scalar() or 0, 1
            )

        # Per-node breakdown
        from sqlalchemy import func
        nodes = {}
        rows = (
            self.db.query(AITrace.node_name, func.count(), func.avg(AITrace.latency_ms))
            .group_by(AITrace.node_name)
            .all()
        )
        for name, cnt, avg_ms in rows:
            nodes[name] = {"count": cnt, "avg_latency_ms": round(avg_ms or 0, 1)}

        return {
            "total": total,
            "success": success,
            "error": error,
            "avg_latency_ms": avg_latency,
            "by_node": nodes,
        }


class _TraceContext:
    """Internal context manager for a single trace span."""

    def __init__(self, db: Session, node_name: str, session_id: str, trace_type: str,
                 model_name: str, metadata: dict):
        self.db = db
        self.trace_id = uuid.uuid4().hex[:12]
        self.node_name = node_name
        self.session_id = session_id
        self.trace_type = trace_type
        self.model_name = model_name
        self.metadata = metadata
        self.input = ""
        self.output = ""
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency = int((time.time() - self.start_time) * 1000)
        status = "error" if exc_type else "success"
        error_msg = str(exc_val)[:500] if exc_val else None

        record = AITrace(
            trace_id=self.trace_id,
            session_id=self.session_id or "",
            node_name=self.node_name,
            trace_type=self.trace_type,
            model_name=self.model_name or "",
            input_summary=str(self.input)[:200] if self.input else "",
            output_summary=str(self.output)[:500] if self.output else "",
            status=status,
            latency_ms=latency,
            token_count=estimate_tokens(str(self.input)) + estimate_tokens(str(self.output)),
            error_msg=error_msg,
            metadata_json=json.dumps(self.metadata, ensure_ascii=False) if self.metadata else None,
        )
        try:
            self.db.add(record)
            self.db.commit()
        except Exception:
            logger.warning(
                "Failed to commit trace node=%s trace_id=%s — rolling back session",
                self.node_name, self.trace_id, exc_info=True,
            )
            try:
                self.db.rollback()
            except Exception:
                logger.exception("Rollback also failed for trace_id=%s", self.trace_id)

        return False  # Don't suppress exceptions
