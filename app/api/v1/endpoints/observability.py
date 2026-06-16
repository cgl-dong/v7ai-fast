"""Observability API — AI trace queries + rating for Admin panel."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from app.core.database import get_db
from app.services.observability import Tracer
from app.services.rating import RatingService

router = APIRouter()


class RatingRequest(BaseModel):
    target_type: str = Field(..., description="trace 或 observation")
    target_id: str = Field(..., description="target ID")
    session_id: str = ""
    node_name: str = ""
    scorer: str = ""
    rater_type: str = "human"
    judge_model: str = ""
    dimension_scores: dict = Field(..., description="维度评分，如 {'accuracy': 4, 'fluency': 5}")
    dimension_reasons: dict = None
    comment: str = ""


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


# ── Rating endpoints ──────────────────────────────────────────────

@router.post("/ratings")
async def create_rating(req: RatingRequest, db: Session = Depends(get_db)):
    """创建或更新评分（同一 scorer 对同一 target 重复提交会更新）"""
    svc = RatingService(db)
    result = svc.rate(
        target_type=req.target_type,
        target_id=req.target_id,
        dimension_scores=req.dimension_scores,
        session_id=req.session_id,
        node_name=req.node_name,
        scorer=req.scorer,
        comment=req.comment,
        rater_type=req.rater_type or "human",
        judge_model=req.judge_model or "",
        dimension_reasons=req.dimension_reasons,
    )
    return {
        "id": result.id,
        "target_type": result.target_type,
        "target_id": result.target_id,
        "overall_score": result.overall_score,
        "message": "评分已保存",
    }


@router.get("/ratings")
async def list_ratings(
    target_type: str = Query(None, description="trace 或 observation"),
    target_id: str = Query(None),
    session_id: str = Query(None),
    rater_type: str = Query(None, description="ai 或 human"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """查询评分记录，支持按评价来源过滤"""
    svc = RatingService(db)
    ratings = svc.query_ratings(target_type=target_type, target_id=target_id, session_id=session_id, limit=limit)
    if rater_type:
        ratings = [r for r in ratings if r.get("rater_type") == rater_type]
    return {"ratings": ratings, "count": len(ratings)}


@router.get("/ratings/stats")
async def rating_stats(
    target_type: str = Query(None, description="trace 或 observation"),
    node_name: str = Query(None),
    rater_type: str = Query(None, description="ai 或 human, 不传则全部"),
    db: Session = Depends(get_db),
):
    """获取评分统计：平均分、各维度得分、按节点分组。
    支持按 rater_type 过滤，对比 AI 裁判 vs 人工评分。"""
    svc = RatingService(db)
    return svc.stats(target_type=target_type, node_name=node_name, rater_type=rater_type)


@router.get("/ratings/compare")
async def compare_ratings(
    node_name: str = Query(None, description="节点名"),
    db: Session = Depends(get_db),
):
    """对比 AI 裁判 vs 人工评分的统计差异"""
    svc = RatingService(db)
    ai_stats = svc.stats(node_name=node_name, rater_type="ai")
    human_stats = svc.stats(node_name=node_name, rater_type="human")
    return {
        "ai": {"total": ai_stats["total"], "avg_overall": ai_stats["avg_overall"], "by_dimension": ai_stats["by_dimension"]},
        "human": {"total": human_stats["total"], "avg_overall": human_stats["avg_overall"], "by_dimension": human_stats["by_dimension"]},
    }


@router.get("/ratings/dimensions")
async def rating_dimensions(
    target_type: str = Query(..., description="trace 或 observation"),
    node_name: str = Query(None, description="节点名(observation时使用)"),
    db: Session = Depends(get_db),
):
    """获取指定目标的评分维度定义（前端用于渲染评分表单）"""
    svc = RatingService(db)
    return {"dimensions": svc.dimensions_for_target(target_type, node_name)}
