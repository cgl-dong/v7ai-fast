"""Agent tools package — Day2 Function Calling integration.

Aggregates all tools into the global registry. Import this package to
register every built-in tool:

    from app.services import tools  # registers calculator, web_search, ...
    from app.services.tools.base import registry
    TOOLS = registry.schemas()      # OpenAI tools array
"""
import logging

from app.services.tools.base import BaseTool, ToolRegistry, registry
from app.services.tools.calculator import calculator_tool
from app.services.tools.web_search import web_search_tool
from app.services.tools.qcc import qcc_tool

logger = logging.getLogger(__name__)

# ── Register all built-in tools ────────────────────────────────────
_ALL_TOOLS: list = [
    calculator_tool,
    web_search_tool,
    qcc_tool,
]

for _tool in _ALL_TOOLS:
    registry.register(_tool)


def get_tool(name: str):
    """Get a registered tool instance by name."""
    return registry.get(name)


def all_tool_schemas() -> list:
    """OpenAI-compatible tools array for LLM requests."""
    return registry.schemas()


def execute_tool(name: str, **kwargs) -> str:
    """Execute a tool by name with kwargs. Returns result text.
    Returns an error string if the tool doesn't exist or fails.
    """
    tool = registry.get(name)
    if tool is None:
        return f"错误：不存在工具 {name}"
    try:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(tool.execute(**kwargs))
    except Exception as e:
        logger.error(f"[tool:{name}] execute failed: {e}")
        return f"工具执行异常：{str(e)}"


__all__ = [
    "BaseTool",
    "ToolRegistry",
    "registry",
    "get_tool",
    "all_tool_schemas",
    "execute_tool",
]
