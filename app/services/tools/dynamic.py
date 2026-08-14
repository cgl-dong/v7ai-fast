"""Dynamic tools — user-created tools stored in DB, loaded into the registry.

Two tool types:
  - http:   configurable HTTP call (method/url/headers), params map to query/body
  - python: arbitrary Python function (advanced, admin-only by convention)

Dynamic tools register into the global registry at startup and on create/update.
"""
import json
import logging
from typing import Dict, Any, Optional

import httpx

from app.services.tools.base import BaseTool, registry

logger = logging.getLogger(__name__)


class DynamicHttpTool(BaseTool):
    """Tool that calls an external HTTP API."""

    tool_type = "http"

    def __init__(self, name: str, description: str, parameters: Dict[str, Any],
                 config: Dict[str, Any]):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.url = config.get("url", "")
        self.method = config.get("method", "GET").upper()
        self.headers = config.get("headers", {})
        self.timeout = httpx.Timeout(config.get("timeout", 30.0))
        self._dynamic = True

    async def execute(self, **kwargs) -> str:
        if not self.url:
            return "工具配置错误：缺少 URL"
        try:
            headers = {**self.headers, "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if self.method == "GET":
                    resp = await client.get(self.url, params=kwargs, headers=headers)
                elif self.method == "POST":
                    resp = await client.post(self.url, json=kwargs, headers=headers)
                else:
                    resp = await client.request(self.method, self.url, json=kwargs, headers=headers)
            try:
                data = resp.json()
                return json.dumps(data, ensure_ascii=False)[:2000]
            except Exception:
                return resp.text[:2000]
        except Exception as e:
            return f"HTTP 调用失败：{str(e)}"


class DynamicPythonTool(BaseTool):
    """Tool backed by a Python function body (advanced)."""

    tool_type = "python"

    def __init__(self, name: str, description: str, parameters: Dict[str, Any],
                 config: Dict[str, Any]):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.code = config.get("code", "")
        self._dynamic = True

    async def execute(self, **kwargs) -> str:
        if not self.code.strip():
            return "工具配置错误：缺少代码"
        try:
            # Use a single namespace dict for both globals and locals so that
            # modules imported in the code are visible inside run().
            ns: Dict[str, Any] = {
                "__builtins__": __builtins__,
                "__name__": "__main__",
            }
            exec(compile(self.code, f"<tool:{self.name}>", "exec"), ns)
            fn = ns.get("run")
            if fn is None:
                return "工具代码错误：必须定义 run(**kwargs) 函数并返回字符串"
            result = fn(**kwargs)
            return str(result)[:2000]
        except Exception as e:
            return f"工具执行异常：{str(e)}"


def build_tool_from_row(name: str, description: str, parameters: str,
                        tool_type: str, config: str) -> Optional[BaseTool]:
    """Build a BaseTool instance from DB row fields. Returns None on bad config."""
    try:
        params = json.loads(parameters) if parameters else {"type": "object", "properties": {}}
        cfg = json.loads(config) if config else {}
    except json.JSONDecodeError as e:
        logger.error(f"[tool:{name}] config JSON 解析失败: {e}")
        return None

    if tool_type == "http":
        return DynamicHttpTool(name, description, params, cfg)
    elif tool_type == "python":
        return DynamicPythonTool(name, description, params, cfg)
    logger.error(f"[tool:{name}] 未知工具类型: {tool_type}")
    return None


def load_dynamic_tools_from_db(db) -> int:
    """Load all active dynamic tools from DB into the registry.
    Returns count registered. Removes dynamic tools no longer in DB.
    """
    from app.core.database import ToolDefinition

    # Remove previously-loaded dynamic tools
    stale = [t.name for t in registry.all_tools() if getattr(t, "_dynamic", False)]
    for name in stale:
        registry._tools.pop(name, None)

    count = 0
    try:
        rows = db.query(ToolDefinition).filter(ToolDefinition.is_active == True).all()
        for row in rows:
            tool = build_tool_from_row(row.name, row.description, row.parameters,
                                       row.tool_type, row.config)
            if tool:
                registry.register(tool)
                count += 1
    except Exception as e:
        logger.warning(f"[dynamic-tools] load failed: {e}")
    logger.info(f"[dynamic-tools] loaded {count} dynamic tools from DB")
    return count


def register_dynamic_tool(db, row) -> bool:
    """Register (or update) a single dynamic tool in the registry."""
    tool = build_tool_from_row(row.name, row.description, row.parameters,
                               row.tool_type, row.config)
    if not tool:
        return False
    registry.register(tool)
    return True


def unregister_dynamic_tool(name: str) -> None:
    """Remove a dynamic tool from the registry (if it is dynamic)."""
    t = registry.get(name)
    if t and getattr(t, "_dynamic", False):
        registry._tools.pop(name, None)
        logger.info(f"[dynamic-tools] unregistered: {name}")
