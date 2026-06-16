"""AI Judge — LLM-as-Judge 自动评价系统.

用独立模型对 Agent 回答进行多维度质量评分, 与人工评分并存, 形成双轨评价体系。

核心设计:
  - 使用独立 prompt 模板, 要求输出严格 JSON
  - 低 temperature (0.1) 保证评分一致性
  - 每个维度附带评价理由 (dimension_reasons)
  - 异步 fire-and-forget, 不阻塞主流程
  - 结果存入 trace_ratings 表, rater_type="ai"
"""

import json
import asyncio
import logging
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services.deepseek import AIService
from app.services.rating import RatingService, NODE_DIMENSIONS, DIMENSION_LABELS, compute_overall

logger = logging.getLogger(__name__)

# ── Judge prompt templates ────────────────────────────────────────

JUDGE_PROMPT_RAG = """你是 AI 质量评审专家。请基于以下信息, 对 AI 助手的回答进行多维度打分。

【用户问题】
{question}

【知识库检索到的文档内容】
{context}

【AI 回答】
{answer}

【评分维度及标准 (1-5分)】
{dimensions_desc}

【评审要求】
1. 逐维度打分, 1分最差 5分最佳
2. 每个维度附带 1-2 句中文评价理由
3. 最后给出综合评语 (30字以内)
4. 严格输出 JSON, 不要其他文字

输出格式:
{{"scores": {{"维度名": 分数, ...}}, "reasons": {{"维度名": "理由", ...}}, "comment": "综合评语"}}"""

JUDGE_PROMPT_DIRECT = """你是 AI 质量评审专家。请对 AI 助手的回答进行多维度打分。

【用户问题】
{question}

【AI 回答】
{answer}

【评分维度及标准 (1-5分)】
{dimensions_desc}

【评审要求】
1. 逐维度打分, 1分最差 5分最佳
2. 每个维度附带 1-2 句中文评价理由
3. 最后给出综合评语 (30字以内)
4. 严格输出 JSON, 不要其他文字

输出格式:
{{"scores": {{"维度名": 分数, ...}}, "reasons": {{"维度名": "理由", ...}}, "comment": "综合评语"}}"""


def _build_dimensions_desc(node_name: str) -> str:
    """Build dimension description text for the judge prompt."""
    dims = NODE_DIMENSIONS.get(node_name, NODE_DIMENSIONS.get("__trace__", []))
    lines = []
    for d in dims:
        label = DIMENSION_LABELS.get(d, d)
        lines.append(f"- {d} ({label}): 1=极差, 3=一般, 5=优秀")
    return "\n".join(lines)


class AIJudge:
    """LLM-as-Judge: 用独立模型自动评价 Agent 回答质量。

    Usage:
        judge = AIJudge(db)
        # 异步后台执行, 不阻塞
        asyncio.create_task(judge.evaluate_trace(
            question="...", context="...", answer="...",
            trace_id="abc123", session_id="sess1",
            node_name="generate_with_docs"
        ))
    """

    def __init__(self, db: Session):
        self.db = db
        self.enabled = settings.judge_enabled
        self.judge_model = settings.judge_model or settings.deepseek_model or "deepseek-chat"
        self.temperature = settings.judge_temperature

    def _get_ai(self) -> AIService:
        """Create AI service for judge calls with low temperature for consistency."""
        from app.services.model_config import ModelConfigService
        svc = ModelConfigService(self.db)
        active = svc.get_active_config("llm")
        if active and active.api_key:
            return AIService(api_key=active.api_key, model=self.judge_model, api_url=active.api_url, temperature=self.temperature)
        return AIService(model=self.judge_model, temperature=self.temperature)

    async def evaluate_trace(
        self,
        question: str,
        answer: str,
        trace_id: str,
        session_id: str = "",
        context: str = "",
        node_name: str = "generate",
    ):
        """Evaluate a single trace (one conversation turn). Async, fire-and-forget.

        Args:
            question: 用户问题
            answer: Agent 回答
            trace_id: 追踪 ID
            session_id: 会话 ID
            context: 检索到的知识库内容 (可选)
            node_name: 节点名称, 决定评分维度
        """
        if not self.enabled:
            logger.debug("AI Judge disabled, skip evaluation")
            return

        try:
            # Build prompt
            dims_desc = _build_dimensions_desc(node_name)
            if context:
                prompt = JUDGE_PROMPT_RAG.format(
                    question=question, context=context[:3000],
                    answer=answer[:2000], dimensions_desc=dims_desc
                )
            else:
                prompt = JUDGE_PROMPT_DIRECT.format(
                    question=question, answer=answer[:2000], dimensions_desc=dims_desc
                )

            # Call judge model
            ai = self._get_ai()

            resp = await ai.call_model(prompt)
            scores, reasons, comment = self._parse_judge_response(resp)

            if not scores:
                logger.warning(f"Judge returned no valid scores for trace {trace_id}")
                return

            # Persist to DB
            rating_svc = RatingService(self.db)
            rating_svc.rate(
                target_type="trace",
                target_id=trace_id,
                dimension_scores=scores,
                session_id=session_id,
                node_name="",
                scorer=f"ai_judge_{self.judge_model}",
                comment=comment,
                rater_type="ai",
                judge_model=self.judge_model,
                dimension_reasons=reasons,
            )
            logger.info(f"AI Judge scored trace {trace_id}: {compute_overall(scores)}/5")

        except Exception as e:
            logger.error(f"AI Judge evaluation failed for trace {trace_id}: {e}")

    def _parse_judge_response(self, resp: str) -> tuple:
        """Parse judge LLM response JSON. Returns (scores, reasons, comment)."""
        try:
            # Strip markdown code blocks if any
            json_str = resp.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```", 2)[1]
                json_str = json_str.replace("json", "", 1).strip()

            data = json.loads(json_str)
            scores = data.get("scores", {})
            reasons = data.get("reasons", {})
            comment = data.get("comment", "")

            # Validate scores are ints 1-5
            clean_scores = {}
            for k, v in scores.items():
                try:
                    sv = int(v)
                    clean_scores[k] = max(1, min(5, sv))
                except (ValueError, TypeError):
                    clean_scores[k] = 3  # default neutral

            return clean_scores, reasons, comment
        except json.JSONDecodeError:
            logger.warning(f"Judge returned invalid JSON: {resp[:200]}")
            # Fallback: try to extract any JSON-like content
            import re
            match = re.search(r'\{[\s\S]*\}', resp)
            if match:
                try:
                    data = json.loads(match.group())
                    return data.get("scores", {}) or {}, data.get("reasons", {}) or {}, data.get("comment", "") or ""
                except json.JSONDecodeError:
                    pass
            return {}, {}, ""


async def evaluate_agent_response(
    question: str,
    answer: str,
    trace_id: str,
    session_id: str = "",
    context: str = "",
    node_name: str = "generate",
):
    """Convenience: evaluate agent response in background. Creates its own DB session.

    Usage in agent flow:
        asyncio.create_task(evaluate_agent_response(question, answer, trace_id, ...))
    """
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        judge = AIJudge(db)
        await judge.evaluate_trace(
            question=question,
            answer=answer,
            trace_id=trace_id,
            session_id=session_id,
            context=context,
            node_name=node_name,
        )
    finally:
        db.close()
