"""Web search tool — wraps the existing WebSearch service as an agent tool."""
import logging
from app.services.tools.base import BaseTool
from app.services.web_search import WebSearch

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    """联网搜索实时信息。"""

    name = "web_search"
    description = (
        "联网搜索实时信息，如天气、新闻、股价、最新政策、当前日期等"
        "模型训练数据截止后无法获取的时效性信息。"
        "当用户询问实时/最新信息时使用，返回搜索结果的标题、链接和摘要。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，建议使用简洁的关键词组合"},
        },
        "required": ["query"],
    }

    async def execute(self, query: str) -> str:
        svc = WebSearch()
        if not svc.enabled:
            return "联网搜索未启用（服务端 WEB_SEARCH_ENABLED 未开启）"
        results = await svc.search(query)
        if not results:
            return "未找到相关搜索结果"
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "").strip()
            url = r.get("url", "").strip()
            snippet = r.get("snippet", "").strip()
            lines.append(f"{i}. {title} | {url}\n   {snippet}")
        return "\n".join(lines)


web_search_tool = WebSearchTool()
