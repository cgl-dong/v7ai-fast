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
from app.services.web_search import WebSearch
from app.core.settings import settings

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
    need_type: str               # "direct" | "kb" | "web" — classify结果
    kb_id: Optional[int]
    rewritten_queries: List[str]   # Multi-Query rewritten variants
    hyde_text: Optional[str]       # HyDE hypothetical answer
    kb_results: List[dict]
    web_results: List[dict]        # Web search results (raw)
    context: str                   # 最终上下文（KB + Web 融合）
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
        workflow.add_node("rewrite", self._rewrite_node)
        workflow.add_node("retrieve", self._retrieve_node)
        workflow.add_node("web_search", self._web_search_node)
        workflow.add_node("generate", self._generate_node)

        workflow.set_entry_point("classify")

        # Three-way classify routing
        def route_after_classify(state: RAGState) -> Literal["rewrite", "web_search", "generate"]:
            nt = state.get("need_type", "direct")
            if nt == "kb":
                return "rewrite"
            elif nt == "web":
                return "web_search"
            return "generate"

        workflow.add_conditional_edges("classify", route_after_classify, {
            "rewrite": "rewrite",
            "web_search": "web_search",
            "generate": "generate",
        })
        workflow.add_edge("rewrite", "retrieve")

        # After KB retrieval: if results are insufficient, supplement with web search
        def route_after_retrieve(state: RAGState) -> Literal["web_search", "generate"]:
            kb_results = state.get("kb_results", [])
            # If no KB results or top result similarity is below threshold, supplement with web
            if not kb_results:
                logger.info("[route] no KB results → supplementing with web search")
                return "web_search"
            top_sim = kb_results[0].get("similarity", 0)
            if top_sim < settings.web_search_fallback_threshold:
                logger.info(f"[route] KB top_sim={top_sim:.3f} < threshold={settings.web_search_fallback_threshold} → supplementing with web")
                return "web_search"
            logger.info(f"[route] KB results sufficient (top_sim={top_sim:.3f}) → generate")
            return "generate"

        workflow.add_conditional_edges("retrieve", route_after_retrieve, {
            "web_search": "web_search",
            "generate": "generate",
        })
        workflow.add_edge("web_search", "generate")
        workflow.add_edge("generate", END)

        return workflow.compile()

    async def _classify_node(self, state: RAGState) -> dict:
        question = state["question"]

        # If need_type is already pre-set (e.g. use_kb=False + use_web=True), skip classify
        preset = state.get("need_type", "")
        if preset in ("web", "direct"):
            logger.info(f"[classify] skipping — pre-set need_type={preset}")
            return {"need_type": preset}

        logger.info(f"[classify] question: {question[:100]}...")

        prompt = f"""判断用户问题类型，从以下三种中选择一种：

1. direct — 不需要检索任何外部信息。闲聊问候、通用知识、代码编写、翻译、计算、创意写作、角色扮演
2. kb — 需要查企业知识库。询问公司内部数据、报表、文档内容、内部规章、项目信息、产品参数
3. web — 需要联网搜索实时信息。新闻事件、股票股价、天气预报、今日日期、最新政策、名人近况、比赛结果

问题: {question}

输出JSON: {{"type": "direct/kb/web", "reason": "理由"}}

注意：
- 如果不确定，优先选 kb（知识库）
- 只有明确需要实时/时效性信息时，才选 web
- 通用知识和闲聊一律选 direct"""

        with self.tracer.trace("classify", self.session_id, "agent_node", self.model_name) as ctx:
            ctx.input = question
            try:
                logger.debug(f"[classify] calling LLM (model={self.model_name})")
                answer = await self.ai.call_model(prompt)
                json_str = answer.strip()
                if "```" in json_str:
                    json_str = json_str.split("```")[1].replace("json", "", 1)
                result = json.loads(json_str)
                need_type = result.get("type", "direct")
                reason = result.get("reason", "")
                ctx.output = f"need_type={need_type}"
                ctx.metadata["reason"] = reason
                logger.info(f"[classify] result: type={need_type}, reason={reason}")
                return {"need_type": need_type}
            except Exception as e:
                logger.warning(f"[classify] failed: {e}, defaulting to need_type=kb")
                return {"need_type": "kb"}

    async def _rewrite_node(self, state: RAGState) -> dict:
        """Query Rewrite: Multi-Query + HyDE for better retrieval.
        
        Multi-Query: generate 2-3 keyword-optimized search queries from the original question.
        HyDE: generate a hypothetical answer to bridge the semantic gap.
        """
        question = state["question"]
        history = _format_history(state.get("messages", []), max_turns=3)

        if not settings.rag_query_rewrite_enabled:
            logger.info(f"[rewrite] disabled, using original query")
            return {"rewritten_queries": [question], "hyde_text": None}

        logger.info(f"[rewrite] rewriting query: {question[:100]}...")

        history_block = f"对话历史:\n{history}\n" if history else ""

        prompt = f"""你是一个搜索查询优化器。将用户问题改写为2-3个更适合知识库检索的关键词查询。
同时生成一段假设答案(HyDE)，帮助弥合问题和文档之间的语义差距。

{history_block}用户问题: {question}

输出JSON格式:
{{"queries": ["优化查询1", "优化查询2", "优化查询3"], "hyde": "假设答案内容"}}

要求:
- queries: 2-3个独立检索查询，使用关键词+实体词组合，去除冗余语气词
- hyde: 用1-3句话写一个对问题的假设回答（类似知识库中可能包含的内容）
- 仅输出JSON, 不要其他文字"""

        with self.tracer.trace("rewrite", self.session_id, "agent_node", self.model_name) as ctx:
            ctx.input = question[:200]
            try:
                answer = await self.ai.call_model(prompt)
                json_str = answer.strip()
                if "```" in json_str:
                    json_str = json_str.split("```")[1].replace("json", "", 1).strip()
                result = json.loads(json_str)
                queries = result.get("queries", [question])
                hyde = result.get("hyde", "")
                
                if not queries or len(queries) == 0:
                    queries = [question]
                
                ctx.output = f"queries={len(queries)}, hyde_len={len(hyde)}"
                ctx.metadata["queries"] = queries
                ctx.metadata["has_hyde"] = bool(hyde)
                
                logger.info(f"[rewrite] generated {len(queries)} queries, hyde={len(hyde)} chars")
                for i, q in enumerate(queries):
                    logger.info(f"[rewrite]   query[{i}]: {q[:120]}")
                if hyde:
                    logger.info(f"[rewrite]   hyde: {hyde[:200]}...")
                
                return {"rewritten_queries": queries, "hyde_text": hyde}
            except Exception as e:
                logger.warning(f"[rewrite] failed: {e}, using original query")
                return {"rewritten_queries": [question], "hyde_text": None}

    async def _retrieve_node(self, state: RAGState) -> dict:
        kb_id = state.get("kb_id")
        question = state["question"]
        # Use rewritten queries if available, fallback to original question
        search_queries = state.get("rewritten_queries", [question]) or [question]
        hyde_text = state.get("hyde_text", "")

        logger.info(f"[retrieve] searching (kb_id={kb_id}, top_k=5, num_queries={len(search_queries)}): {question[:80]}...")

        with self.tracer.trace("retrieve", self.session_id, "agent_node", "",
                               {"need_type": "kb", "kb_id": kb_id}) as ctx:
            ctx.input = question[:200]
            try:
                indexer = Indexer(self.db)
                
                # Search with each rewritten query + HyDE, collect all results
                all_results = []
                seen_ids = set()
                
                # Primary search: use first rewritten query (best quality)
                for sq in search_queries[:2]:  # Limit to 2 queries for latency
                    results = indexer.search_chunks(sq, top_k=5, kb_id=kb_id, user_id=self.user_id)
                    for r in results:
                        if r["id"] not in seen_ids:
                            seen_ids.add(r["id"])
                            all_results.append(r)
                
                # If HyDE was generated, also search with it
                if hyde_text and len(hyde_text) > 10:
                    hyde_results = indexer.search_chunks(hyde_text, top_k=5, kb_id=kb_id, user_id=self.user_id)
                    for r in hyde_results:
                        if r["id"] not in seen_ids:
                            seen_ids.add(r["id"])
                            all_results.append(r)
                    logger.info(f"[retrieve] HyDE search added {len([r for r in hyde_results if r['id'] not in seen_ids or True])} results")
                
                # Sort by similarity, take top 5
                all_results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
                results = all_results[:5]
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

    async def _web_search_node(self, state: RAGState) -> dict:
        """Web search node — queries the configured search provider and
        merges results into the state context.

        Can be triggered by:
          - classify: need_type="web" (user explicitly asked for realtime info)
          - route_after_retrieve: KB results insufficient, supplement with web
        """
        question = state["question"]
        kb_context = state.get("context", "")

        logger.info(f"[web_search] searching: {question[:80]}...")

        with self.tracer.trace("web_search", self.session_id, "agent_node", "") as ctx:
            ctx.input = question[:200]
            try:
                svc = WebSearch()
                raw_results = await svc.search(question)
                web_context = svc.format_results(raw_results)

                ctx.output = f"found {len(raw_results)} web results"
                ctx.metadata["result_count"] = len(raw_results)
                ctx.metadata["provider"] = svc.provider

                logger.info(f"[web_search] got {len(raw_results)} results from {svc.provider}")

                # Merge KB context + web context
                if kb_context and web_context:
                    merged = (
                        f"【企业知识库内容】\n{kb_context}\n\n"
                        f"【网络搜索结果】\n{web_context}"
                    )
                    logger.info(f"[web_search] merged KB + web context ({len(kb_context)} + {len(web_context)} chars)")
                elif web_context:
                    merged = web_context
                else:
                    merged = kb_context or ""

                return {
                    "context": merged,
                    "web_results": raw_results,
                }

            except Exception as e:
                logger.error(f"[web_search] error: {e}")
                # Fallback: keep whatever KB context already exists
                return {
                    "context": kb_context,
                    "web_results": [],
                    "error": str(e),
                }

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
            # Detect if web search results are present in context
            has_web = bool(state.get("web_results"))
            if has_web:
                prompt = f"""你是一个智能助手，整合了企业知识库和网络搜索结果来回答用户问题。

{history}参考信息:
{context}

用户问题: {question}

要求:
- 优先使用企业知识库内容回答内部业务问题
- 使用网络搜索结果回答实时/时效性问题
- 综合两类信息时说明信息来源
- 信息不足时如实说明
- 用中文，简洁专业"""
            else:
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

    async def run(self, message: str, chat_history: List[dict] = None, use_kb: bool = True, kb_id: int = None, use_web: bool = True) -> str:
        """Main entry point: question → graph → answer.

        Args:
            message: User question
            chat_history: Previous conversation turns
            use_kb: If False, skip retrieval entirely and answer directly
            kb_id: Optional knowledge base ID to scope retrieval
            use_web: If False, skip web search even when classify suggests it
        """
        import time
        t0 = time.time()
        logger.info(f"[agent] start: use_kb={use_kb}, use_web={use_web}, kb_id={kb_id}, session={self.session_id}, "
                    f"question={message[:80]}...")

        web_enabled = settings.web_search_enabled and use_web

        # Fast path: user wants direct answer without any retrieval
        if not use_kb and not web_enabled:
            logger.info(f"[agent] direct mode (use_kb=False, use_web=False), model={self.model_name}")
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

        # Classify and route: if use_kb is off but use_web is on, force "web" type
        if not use_kb and web_enabled:
            need_type = "web"
            logger.info(f"[agent] use_kb=False, use_web=True → forcing need_type=web")
        else:
            classify_state = {"question": message, "messages": chat_history or []}
            result = await self._classify_node(classify_state)
            need_type = result.get("need_type", "kb")

        logger.info(f"[agent] RAG mode, need_type={need_type}, model={self.model_name}")
        state: RAGState = {
            "question": message,
            "messages": chat_history or [],
            "need_type": need_type,
            "kb_id": kb_id,
            "rewritten_queries": [],
            "hyde_text": None,
            "kb_results": [],
            "web_results": [],
            "context": "",
            "answer": "",
            "error": None,
        }
        try:
            result = await self.graph.ainvoke(state)
            answer = result.get("answer", "未能生成回答")
            context = result.get("context", "")
            elapsed = time.time() - t0
            need_type = result.get("need_type", "direct")
            logger.info(f"[agent] RAG done: need_type={need_type}, context={len(context)} chars, "
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
                         use_kb: bool = True, kb_id: int = None, use_web: bool = True):
        """Streaming version: same pipeline, yields SSE-ready tokens.

        Uses classify+retrieve (non-streaming, fast), then streams the generate step.
        """
        import time, asyncio
        t0 = time.time()
        messages_list = chat_history or []
        logger.info(f"[agent-stream] start: use_kb={use_kb}, use_web={use_web}, kb_id={kb_id}, session={self.session_id}")

        web_enabled = settings.web_search_enabled and use_web

        # ── Classify ──────────────
        need_type = "kb" if use_kb else "direct"
        if use_web and not use_kb:
            need_type = "web"
            logger.info("[agent-stream] use_kb=False, use_web=True → need_type=web")
        elif use_kb:
            classify_state = {"question": message, "messages": messages_list}
            result = await self._classify_node(classify_state)
            need_type = result.get("need_type", "kb")

        # ── Retrieve & Web Search ──
        context = ""
        kb_results = []
        web_results = []
        if need_type == "kb":
            retrieve_state = {
                "question": message, "kb_id": kb_id, "need_type": "kb",
                "messages": messages_list,
            }
            result = await self._retrieve_node(retrieve_state)
            context = result.get("context", "")
            kb_results = result.get("kb_results", [])

            # KB results insufficient? supplement with web search
            if not kb_results or kb_results[0].get("similarity", 0) < settings.web_search_fallback_threshold:
                if web_enabled:
                    web_state = {"question": message, "context": context, "kb_id": kb_id}
                    web_result = await self._web_search_node(web_state)
                    context = web_result.get("context", context)
                    web_results = web_result.get("web_results", [])

        elif need_type == "web":
            if web_enabled:
                web_state = {"question": message, "context": "", "kb_id": kb_id}
                web_result = await self._web_search_node(web_state)
                context = web_result.get("context", "")
                web_results = web_result.get("web_results", [])

        self._last_sources = kb_results or web_results

        # ── Generate (streaming) ──
        if context:
            has_web = bool(web_results)
            history = _format_history(messages_list)
            all_msgs = messages_list
            if len(all_msgs) > 6:
                summary = await _summarize_history(self.ai, all_msgs[:-4])
                if summary:
                    history = f"[对话背景摘要]\n{summary}\n\n{history}"
            if has_web:
                prompt = f"""你是一个智能助手，整合了企业知识库和网络搜索结果来回答用户问题。

{history}参考信息:
{context}

用户问题: {message}

要求:
- 优先使用企业知识库内容回答内部业务问题
- 使用网络搜索结果回答实时/时效性问题
- 综合两类信息时说明信息来源
- 信息不足时如实说明
- 用中文，简洁专业"""
            else:
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
