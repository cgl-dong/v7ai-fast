"""Observability API — AI trace queries for Admin panel."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.observability import Tracer

router = APIRouter()


@router.get("/traces")
async def list_traces(
    session_id: str = Query(None),
    node_name: str = Query(None),
    status: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """查询 AI 调用追踪记录"""
    tracer = Tracer(db)
    traces = tracer.query_traces(session_id=session_id, node_name=node_name, status=status, limit=limit)
    return {"traces": traces, "count": len(traces)}


@router.get("/traces/stats")
async def trace_stats(db: Session = Depends(get_db)):
    """获取追踪统计信息"""
    tracer = Tracer(db)
    return tracer.stats()
