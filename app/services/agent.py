"""LangGraph RAG Agent — knowledge-base aware AI assistant with observability tracing."""
import asyncio
import json
import logging
from typing import TypedDict, List, Optional, Literal, Annotated

from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session

from app.services.deepseek import AIService
from app.services.indexer import Indexer
from app.services.model_config import ModelConfigService
from app.services.observability import Tracer
from app.services.judge import evaluate_agent_response

logger = logging.getLogger(__name__)


def _get_ai_service(db: Session) -> AIService:
    """Create AIService using active LLM config from DB."""
    svc = ModelConfigService(db)
    active = svc.get_active_config("llm")
    if active and active.api_key:
        return AIService(api_key=active.api_key, model=active.model_name, api_url=active.api_url)
    return AIService()


def _format_context(docs: list) -> str:
    if not docs:
        return ""
    parts = []
    for i, doc in enumerate(docs):
        src = doc.get("filename", "unknown")
        sim = doc.get("similarity", 0)
        parts.append(f"[来源{i+1}: {src} | 相似度: {sim:.2f}]\n{doc['content']}")
    return "\n\n---\n\n".join(parts)


def _estimate_tokens(text: str) -> int:
    """Rough token estimator: Chinese ~1.5 char/token, EN ~4 char/token."""
    # Count CJK chars
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4)


def _format_history(messages: List[dict], max_turns: int = 5, max_history_tokens: int = 2000) -> str:
    """Format recent chat history for prompt injection.

    Token-budget aware: truncates individual messages and the total count
    to stay within max_history_tokens. Returns empty string if no messages.
    """
    if not messages:
        return ""

    recent = messages[-max_turns * 2:]  # Each turn = user + assistant
    lines = ["[历史对话]"]

    budget = max_history_tokens
    for m in reversed(recent):
        content = m.get("content", "")
        role = "用户" if m.get("role") == "user" else "助手"

        # Truncate long messages to ~200 tokens each
        line = f"{role}: {content[:500]}"
        cost = _estimate_tokens(line)

        if cost > budget:
            # One more message will exceed budget, truncate it further
            available = max(budget - _estimate_tokens(f"{role}: "), 50)
            line = f"{role}: {content[:available * 2]}"  # rough char count
            lines.append(line)
            break

        lines.append(line)
        budget -= cost
        if budget < 100:
            break

    lines.reverse()  # Restore chronological order
    return "\n".join(lines) + "\n\n"


async def _summarize_history(ai_service, messages: List[dict]) -> str:
    """Use LLM to generate a concise summary of conversation history.

    Fires only when history is long enough to benefit from compression.
    Returns a 1-3 sentence Chinese summary.
    """
    if not messages:
        return ""

    # Build a compact transcript
    transcript = "\n".join(
        f"{'用户' if m.get('role')=='user' else '助手'}: {m.get('content','')[:200]}"
        for m in messages[-10:]
    )

    prompt = f"""请用1-3句话总结以下对话的核心内容和背景，仅输出摘要：

{transcript}

摘要："""

    try:
        result = await ai_service.call_model(prompt)
        return result.strip()[:300]
    except Exception:
        return ""


class RAGState(TypedDict):
    question: str
    messages: List[dict]
    needs_kb: bool
    kb_id: Optional[int]
    kb_results: List[dict]
    context: str
    answer: str
    error: Optional[str]


class RAGAgent:
    """High-level wrapper: LangGraph RAG agent for enterprise knowledge Q&A."""

    def __init__(self, db: Session, session_id: str = "", user_id: Optional[int] = None):
        self.db = db
        self.ai = _get_ai_service(db)
        self.tracer = Tracer(db)
        self.session_id = session_id
        self.user_id = user_id
        self.model_name = self.ai.model
        self._last_trace_id = ""  # For AI Judge to reference
        self._last_node_name = ""
        self._last_sources = []    # Last retrieved sources for display
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(RAGState)

        workflow.add_node("classify", self._classify_node)
        workflow.add_node("retrieve", self._retrieve_node)
        workflow.add_node("generate", self._generate_node)

        workflow.set_entry_point("classify")

        def route_after_classify(state: RAGState) -> Literal["retrieve", "generate"]:
            return "retrieve" if state.get("needs_kb") else "generate"

        workflow.add_conditional_edges("classify", route_after_classify, {
            "retrieve": "retrieve", "generate": "generate"
        })
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", END)

        return workflow.compile()

    async def _classify_node(self, state: RAGState) -> dict:
        question = state["question"]
        logger.info(f"[classify] question: {question[:100]}...")

        prompt = f"""判断用户问题是否需要从企业知识库检索。

需要知识库的情况：询问数据、报表、文档内容、内部规章、项目信息
不需要知识库的情况：闲聊问候、通用知识、代码编写、翻译、计算

问题: {question}

输出JSON: {{"need_kb": true/false, "reason": "理由"}}"""

        with self.tracer.trace("classify", self.session_id, "agent_node", self.model_name) as ctx:
            ctx.input = question
            try:
                logger.debug(f"[classify] calling LLM (model={self.model_name})")
                answer = await self.ai.call_model(prompt)
                json_str = answer.strip()
                if "```" in json_str:
                    json_str = json_str.split("```")[1].replace("json", "", 1)
                result = json.loads(json_str)
                needs_kb = result.get("need_kb", False)
                reason = result.get("reason", "")
                ctx.output = f"needs_kb={needs_kb}"
                ctx.metadata["reason"] = reason
                logger.info(f"[classify] result: needs_kb={needs_kb}, reason={reason}")
                return {"needs_kb": needs_kb}
            except Exception as e:
                logger.warning(f"[classify] failed: {e}, defaulting to needs_kb=True")
                return {"needs_kb": True}

    async def _retrieve_node(self, state: RAGState) -> dict:
        if not state.get("needs_kb"):
            logger.info(f"[retrieve] skipped (needs_kb=False)")
            return {"kb_results": [], "context": ""}

        kb_id = state.get("kb_id")
        question = state["question"]
        logger.info(f"[retrieve] searching (kb_id={kb_id}, top_k=5): {question[:80]}...")

        with self.tracer.trace("retrieve", self.session_id, "agent_node", "",
                               {"needs_kb": state.get("needs_kb"), "kb_id": kb_id}) as ctx:
            ctx.input = question[:200]
            try:
                indexer = Indexer(self.db)
                results = indexer.search_chunks(question, top_k=5, kb_id=kb_id, user_id=self.user_id)
                context = _format_context(results)
                ctx.output = f"found {len(results)} chunks"
                ctx.metadata["chunk_count"] = len(results)

                # Log per-chunk details
                for r in results:
                    logger.info(f"[retrieve] chunk {r['chunk_index']} from {r['filename']} "
                                f"(type={r['file_type']}, sim={r['similarity']:.3f}): {r['content'][:80]}...")

                if results:
                    top_sim = results[0]["similarity"]
                    avg_sim = sum(r["similarity"] for r in results) / len(results)
                    logger.info(f"[retrieve] {len(results)} results, top_sim={top_sim:.3f}, avg_sim={avg_sim:.3f}")
                    self._last_sources = results
                else:
                    logger.warning(f"[retrieve] no results found for: {question[:80]}")
                    self._last_sources = []
                return {"kb_results": results, "context": context}
            except Exception as e:
                logger.error(f"[retrieve] error: {e}")
                return {"kb_results": [], "context": "", "error": str(e)}

    async def _generate_node(self, state: RAGState) -> dict:
        question = state["question"]
        context = state.get("context", "")

        has_context = bool(context)
        node_name = "generate_with_docs" if has_context else "generate_no_docs"
        self._last_node_name = node_name

        history = _format_history(state.get("messages", []))

        # If conversation is long, also add a summary for overscroll context
        all_msgs = state.get("messages", [])
        if len(all_msgs) > 6:
            summary = await _summarize_history(self.ai, all_msgs[:-4])  # Summarize older messages
            if summary:
                history = f"[对话背景摘要]\n{summary}\n\n{history}"

        if has_context:
            prompt = f"""你是一个企业知识库助手。请基于以下知识库内容回答。

{history}知识库内容:
{context}

用户问题: {question}

要求: 基于知识库回答，信息不足时如实说明。用中文，简洁专业。"""
            logger.info(f"[{node_name}] RAG mode, history={len(state.get('messages', []))}msgs, "
                        f"context={len(context)} chars, prompt={len(prompt)} chars")
        else:
            prompt = f"{history}问题: {question}\n\n用中文简洁回答。"
            logger.info(f"[{node_name}] direct mode, history={len(state.get('messages', []))}msgs, "
                        f"prompt={len(prompt)} chars")

        with self.tracer.trace(node_name, self.session_id, "agent_node", self.model_name,
                               {"has_context": has_context}) as ctx:
            self._last_trace_id = ctx.trace_id
            ctx.input = question[:200]
            try:
                logger.debug(f"[{node_name}] calling LLM (model={self.model_name})")
                answer = await self.ai.call_model(prompt)
                ctx.output = answer[:500]
                logger.info(f"[{node_name}] answer generated: {len(answer)} chars")
                return {"answer": answer}
            except Exception as e:
                logger.error(f"[{node_name}] error: {e}")
                return {"answer": f"生成回答出错: {e}", "error": str(e)}

    async def run(self, message: str, chat_history: List[dict] = None, use_kb: bool = True, kb_id: int = None) -> str:
        """Main entry point: question → graph → answer.

        Args:
            message: User question
            chat_history: Previous conversation turns
            use_kb: If False, skip retrieval entirely and answer directly
            kb_id: Optional knowledge base ID to scope retrieval
        """
        import time
        t0 = time.time()
        logger.info(f"[agent] start: use_kb={use_kb}, kb_id={kb_id}, session={self.session_id}, "
                    f"question={message[:80]}...")

        # Fast path: user wants direct answer without RAG
        if not use_kb:
            logger.info(f"[agent] direct mode (use_kb=False), model={self.model_name}")
            with self.tracer.trace("generate_direct", self.session_id, "agent_node", self.model_name,
                                   {"use_kb": False}) as ctx:
                self._last_trace_id = ctx.trace_id
                self._last_node_name = "generate_direct"
                ctx.input = message[:200]
                try:
                    answer = await self.ai.call_model(message)
                    ctx.output = answer[:500]
                    _fire_judge(self._last_trace_id, self.session_id, message, answer, "", self._last_node_name)
                    elapsed = time.time() - t0
                    logger.info(f"[agent] direct done: {len(answer)} chars, elapsed={elapsed:.1f}s")
                    return answer
                except Exception as e:
                    elapsed = time.time() - t0
                    logger.error(f"[agent] direct error: {e}, elapsed={elapsed:.1f}s")
                    return f"生成回答出错: {e}"

        logger.info(f"[agent] RAG mode, model={self.model_name}")
        state: RAGState = {
            "question": message,
            "messages": chat_history or [],
            "needs_kb": False,
            "kb_id": kb_id,
            "kb_results": [],
            "context": "",
            "answer": "",
            "error": None,
        }
        try:
            result = await self.graph.ainvoke(state)
            answer = result.get("answer", "未能生成回答")
            context = result.get("context", "")
            elapsed = time.time() - t0
            needs_kb = result.get("needs_kb", False)
            logger.info(f"[agent] RAG done: needs_kb={needs_kb}, context={len(context)} chars, "
                        f"answer={len(answer)} chars, elapsed={elapsed:.1f}s")
            _fire_judge(self._last_trace_id, self.session_id, message, answer, context, self._last_node_name)
            return answer
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"[agent] RAG error: {e}, elapsed={elapsed:.1f}s, falling back")
            with self.tracer.trace("fallback", self.session_id, "agent_node", self.model_name) as ctx:
                self._last_trace_id = ctx.trace_id
                self._last_node_name = "fallback"
                ctx.input = message[:200]
                try:
                    answer = await self.ai.call_model(message)
                    ctx.output = answer[:500]
                    elapsed2 = time.time() - t0
                    logger.info(f"[agent] fallback done: {len(answer)} chars, total_elapsed={elapsed2:.1f}s")
                    _fire_judge(self._last_trace_id, self.session_id, message, answer, "", self._last_node_name)
                    return answer
                except Exception as fe:
                    ctx.metadata["fallback_error"] = str(fe)
                    elapsed2 = time.time() - t0
                    logger.error(f"[agent] fallback failed: {fe}, total_elapsed={elapsed2:.1f}s")
                    return f"处理失败: {e}"

    async def run_stream(self, message: str, chat_history: List[dict] = None,
                         use_kb: bool = True, kb_id: int = None):
        """Streaming version: same pipeline, yields SSE-ready tokens.

        Uses classify+retrieve (non-streaming, fast), then streams the generate step.
        """
        import time, asyncio
        t0 = time.time()
        messages_list = chat_history or []
        logger.info(f"[agent-stream] start: use_kb={use_kb}, kb_id={kb_id}, session={self.session_id}")

        # ── Classify ──────────────
        needs_kb = use_kb
        if use_kb:
            classify_state = {"question": message, "messages": messages_list}
            result = await self._classify_node(classify_state)
            needs_kb = result.get("needs_kb", True)

        # ── Retrieve ──────────────
        context = ""
        kb_results = []
        if needs_kb:
            retrieve_state = {
                "question": message, "kb_id": kb_id, "needs_kb": True,
                "messages": messages_list,
            }
            result = await self._retrieve_node(retrieve_state)
            context = result.get("context", "")
            kb_results = result.get("kb_results", [])
            self._last_sources = kb_results

        # ── Generate (streaming) ──
        if context:
            history = _format_history(messages_list)
            all_msgs = messages_list
            if len(all_msgs) > 6:
                summary = await _summarize_history(self.ai, all_msgs[:-4])
                if summary:
                    history = f"[对话背景摘要]\n{summary}\n\n{history}"
            prompt = f"""你是一个企业知识库助手。请基于以下知识库内容回答。

{history}知识库内容:
{context}

用户问题: {message}

要求: 基于知识库回答，信息不足时如实说明。用中文，简洁专业。"""
        else:
            history = _format_history(messages_list)
            prompt = f"{history}问题: {message}\n\n用中文简洁回答。"

        full_answer = ""
        try:
            async for token in self.ai.call_model_stream(prompt):
                full_answer += token
                yield token
        except Exception as e:
            logger.error(f"[agent-stream] error: {e}")
            yield f"\n[流式输出中断: {e}]"

        elapsed = time.time() - t0
        logger.info(f"[agent-stream] done: answer={len(full_answer)} chars, elapsed={elapsed:.1f}s")
        _fire_judge(self._last_trace_id, self.session_id, message, full_answer, context,
                    "generate_with_docs" if context else "generate_direct")


def _fire_judge(trace_id: str, session_id: str, question: str, answer: str, context: str, node_name: str):
    """Fire-and-forget AI judge evaluation in background. Never blocks the main flow."""
    if not trace_id:
        return
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(evaluate_agent_response(
            question=question, answer=answer,
            trace_id=trace_id, session_id=session_id,
            context=context, node_name=node_name,
        ))
    except Exception as e:
        logger.debug(f"Failed to launch judge: {e}")
