"""LangGraph RAG Agent — knowledge-base aware AI assistant."""
import json
import logging
from typing import TypedDict, List, Optional, Literal, Annotated

from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session

from app.services.deepseek import AIService
from app.services.indexer import Indexer
from app.services.model_config import ModelConfigService

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


class RAGState(TypedDict):
    question: str
    messages: List[dict]
    needs_kb: bool
    kb_results: List[dict]
    context: str
    answer: str
    error: Optional[str]


class RAGAgent:
    """High-level wrapper: LangGraph RAG agent for enterprise knowledge Q&A."""

    def __init__(self, db: Session):
        self.db = db
        self.ai = _get_ai_service(db)
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
        prompt = f"""判断用户问题是否需要从企业知识库检索。

需要知识库的情况：询问数据、报表、文档内容、内部规章、项目信息
不需要知识库的情况：闲聊问候、通用知识、代码编写、翻译、计算

问题: {state['question']}

输出JSON: {{"need_kb": true/false, "reason": "理由"}}"""

        try:
            answer = await self.ai.call_model(prompt)
            json_str = answer.strip()
            if "```" in json_str:
                json_str = json_str.split("```")[1].replace("json", "", 1)
            result = json.loads(json_str)
            return {"needs_kb": result.get("need_kb", False)}
        except Exception as e:
            logger.warning(f"Classify failed: {e}")
            return {"needs_kb": True}

    async def _retrieve_node(self, state: RAGState) -> dict:
        if not state.get("needs_kb"):
            return {"kb_results": [], "context": ""}
        try:
            indexer = Indexer(self.db)
            results = indexer.search_chunks(state["question"], top_k=5)
            context = _format_context(results)
            logger.info(f"Retrieved {len(results)} chunks")
            return {"kb_results": results, "context": context}
        except Exception as e:
            logger.error(f"Retrieve error: {e}")
            return {"kb_results": [], "context": "", "error": str(e)}

    async def _generate_node(self, state: RAGState) -> dict:
        question = state["question"]
        context = state.get("context", "")

        if context:
            prompt = f"""你是一个企业知识库助手。请基于以下知识库内容回答。

知识库内容:
{context}

用户问题: {question}

要求: 基于知识库回答，信息不足时如实说明。用中文，简洁专业。"""
        else:
            prompt = f"问题: {question}\n\n用中文简洁回答。"

        try:
            answer = await self.ai.call_model(prompt)
            return {"answer": answer}
        except Exception as e:
            logger.error(f"Generate error: {e}")
            return {"answer": f"生成回答出错: {e}", "error": str(e)}

    async def run(self, message: str, chat_history: List[dict] = None) -> str:
        """Main entry point: question → graph → answer."""
        state: RAGState = {
            "question": message,
            "messages": chat_history or [],
            "needs_kb": False,
            "kb_results": [],
            "context": "",
            "answer": "",
            "error": None,
        }
        try:
            result = await self.graph.ainvoke(state)
            return result.get("answer", "未能生成回答")
        except Exception as e:
            logger.error(f"Agent error: {e}")
            try:
                return await self.ai.call_model(message)
            except Exception:
                return f"处理失败: {e}"
