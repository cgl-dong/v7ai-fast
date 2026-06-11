"""LangGraph RAG Agent - retrieval-augmented generation with pgvector search.

RAG Best Practices applied:
- Similarity threshold filtering (min_similarity=0.45)
- Source citation with [来源: filename] markers
- Chunk deduplication by content overlap
- Token budget control (max 3000 chars context)
- Multi-turn chat history support
"""
import logging
from typing import List, TypedDict, Literal, Optional
from sqlalchemy.orm import Session

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.core.settings import settings
from app.services.model_config import ModelConfigService
from app.services.indexer import Indexer

logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.45
MAX_CONTEXT_CHARS = 3000
MAX_CHUNKS = 5

SYSTEM_PROMPT = """你是一个企业内部知识库助手。

重要规则：
1. 优先使用提供的参考文档回答问题
2. 回答中必须标注信息来源，格式：[来源: 文件名]
3. 如果多个文档都包含相关信息，综合引用
4. 如果文档中没有相关信息，如实说明并基于通用知识回答
5. 回答要简洁、准确、专业，避免冗余
6. 如有历史对话上下文，结合上下文理解用户意图

# 历史对话上下文
{chat_context}

# 参考文档
{context}

# 用户问题
{question}

请基于以上信息回答。"""


class AgentState(TypedDict):
    question: str
    documents: List[dict]
    has_docs: bool
    answer: str
    chat_history: List[dict]


class RAGAgent:
    """LangGraph-based RAG agent with pgvector retrieval."""

    def __init__(self, db: Session):
        self.db = db
        self.indexer = Indexer(db)
        self._llm = None

    def _get_llm(self) -> ChatOpenAI:
        if self._llm is not None:
            return self._llm

        svc = ModelConfigService(self.db)
        active = svc.get_active_config("llm")

        if active and active.api_key:
            base_url = (active.api_url or "").rstrip("/")
            if base_url.endswith("/chat/completions"):
                base_url = base_url.rsplit("/", 2)[0]
            if not base_url:
                base_url = "https://api.deepseek.com/v1"

            self._llm = ChatOpenAI(
                model=active.model_name or "deepseek-chat",
                api_key=active.api_key,
                base_url=base_url,
                temperature=0.3,  # Lower for more factual RAG responses
                max_tokens=2048,
            )
        else:
            self._llm = ChatOpenAI(
                model=settings.deepseek_model or "deepseek-chat",
                api_key=settings.deepseek_api_key,
                base_url="https://api.deepseek.com/v1",
                temperature=0.3,
                max_tokens=2048,
            )
        return self._llm

    def _retrieve(self, state: AgentState) -> AgentState:
        """Retrieve + filter + deduplicate relevant documents."""
        question = state["question"]
        try:
            raw_docs = self.indexer.search_chunks(question, top_k=MAX_CHUNKS * 2)

            # 1. Filter by similarity threshold
            filtered = [d for d in raw_docs if d.get("similarity", 0) >= MIN_SIMILARITY]
            logger.info(
                f"Retrieved {len(raw_docs)} chunks, "
                f"{len(filtered)} pass similarity threshold ({MIN_SIMILARITY})"
            )

            # 2. Deduplicate: if two chunks from same file have high content overlap, keep only one
            deduped = self._deduplicate_chunks(filtered, max_chunks=MAX_CHUNKS)
            logger.info(f"After dedup: {len(deduped)} chunks")

            state["documents"] = deduped
            state["has_docs"] = len(deduped) > 0
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            state["documents"] = []
            state["has_docs"] = False
        return state

    def _deduplicate_chunks(self, chunks: List[dict], max_chunks: int = MAX_CHUNKS) -> List[dict]:
        """Remove near-duplicate chunks and limit to max_chunks."""
        if len(chunks) <= 1:
            return chunks[:max_chunks]

        result = []
        for chunk in chunks:
            is_dup = False
            for existing in result:
                overlap = self._content_overlap(chunk["content"], existing["content"])
                if overlap > 0.6 and chunk.get("file_type") == existing.get("file_type"):
                    is_dup = True
                    # Keep the one with higher similarity
                    if chunk.get("similarity", 0) > existing.get("similarity", 0):
                        result.remove(existing)
                        result.append(chunk)
                    break
            if not is_dup:
                result.append(chunk)
            if len(result) >= max_chunks:
                break

        return result

    @staticmethod
    def _content_overlap(text1: str, text2: str) -> float:
        """Simple overlap ratio between two texts."""
        words1 = set(text1[:500].split())
        words2 = set(text2[:500].split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        return len(intersection) / min(len(words1), len(words2))

    def _decide_route(self, state: AgentState) -> Literal["generate_with_docs", "generate_no_docs"]:
        return "generate_with_docs" if state["has_docs"] else "generate_no_docs"

    def _build_context(self, documents: List[dict]) -> str:
        """Build context with token budget control."""
        if not documents:
            return "（未找到相关文档）"

        parts = []
        total_chars = 0
        for i, doc in enumerate(documents, 1):
            content = doc["content"]
            filename = doc.get("filename", "unknown")
            similarity = doc.get("similarity", 0)
            chunk_text = f"[文档{i}: {filename} (相关度: {similarity:.0%})]\n{content}\n"

            if total_chars + len(chunk_text) > MAX_CONTEXT_CHARS:
                truncated = chunk_text[:MAX_CONTEXT_CHARS - total_chars] + "..."
                parts.append(truncated)
                break

            parts.append(chunk_text)
            total_chars += len(chunk_text)

        return "\n".join(parts)

    def _build_chat_context(self, history: List[dict]) -> str:
        """Build chat history context."""
        if not history:
            return "（无历史对话）"
        lines = []
        for h in history[-4:]:  # Keep last 4 messages
            role = "用户" if h.get("role") == "user" else "助手"
            lines.append(f"{role}: {h.get('content', '')[:200]}")
        return "\n".join(lines)

    def _generate(self, state: AgentState) -> AgentState:
        llm = self._get_llm()
        context = self._build_context(state["documents"])
        chat_context = self._build_chat_context(state.get("chat_history", []))

        prompt = SYSTEM_PROMPT.format(
            chat_context=chat_context,
            context=context,
            question=state["question"],
        )

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            state["answer"] = response.content
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            state["answer"] = f"AI回答生成失败: {str(e)}"
        return state

    def _generate_no_docs(self, state: AgentState) -> AgentState:
        llm = self._get_llm()
        chat_context = self._build_chat_context(state.get("chat_history", []))

        prompt = f"""你是一个企业内部知识库助手。

# 历史对话上下文
{chat_context}

# 用户问题
{state["question"]}

（知识库中未找到相关文档，请基于你的通用知识回答。如果涉及企业内部信息，请明确说明无法确认。）"""

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            state["answer"] = response.content
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            state["answer"] = f"AI回答生成失败: {str(e)}"
        return state

    def build_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("generate_with_docs", self._generate)
        workflow.add_node("generate_no_docs", self._generate_no_docs)

        workflow.set_entry_point("retrieve")
        workflow.add_conditional_edges(
            "retrieve",
            self._decide_route,
            {"generate_with_docs": "generate_with_docs", "generate_no_docs": "generate_no_docs"},
        )
        workflow.add_edge("generate_with_docs", END)
        workflow.add_edge("generate_no_docs", END)

        return workflow.compile()

    async def run(self, question: str, chat_history: Optional[List[dict]] = None) -> str:
        """Run the RAG agent and return the answer."""
        graph = self.build_graph()
        initial_state: AgentState = {
            "question": question,
            "documents": [],
            "has_docs": False,
            "answer": "",
            "chat_history": chat_history or [],
        }
        try:
            result = graph.invoke(initial_state)
            return result["answer"]
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            try:
                return self._fallback_generate(question)
            except Exception:
                return f"AI 回答生成失败: {str(e)}"

    def _fallback_generate(self, question: str) -> str:
        llm = self._get_llm()
        response = llm.invoke([HumanMessage(content=question)])
        return response.content
