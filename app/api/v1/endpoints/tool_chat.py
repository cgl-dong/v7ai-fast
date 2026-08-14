"""Tool-calling chat endpoint — Day2 Function Calling integration.

POST /api/chat/tool
  { "message": "...", "session_id": "optional", "tools": ["calculator", "web_search"] }
"""
import json
import re
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db, ChatSession, ChatMessage, User
from app.core.logging import logger
from app.services.tool_agent import ToolAgent
from app.services.session import SessionService
from app.services.auth import AuthService
from app.services.tools import registry
from app.api.v1.endpoints.auth import get_current_user

router = APIRouter()


def _get_agent(db: Session) -> ToolAgent:
    """Create ToolAgent with the active LLM config from DB."""
    from app.services.model_config import ModelConfigService
    svc = ModelConfigService(db)
    active = svc.get_active_config("llm")
    if active and active.api_key:
        from app.services.deepseek import AIService
        return ToolAgent(AIService(api_key=active.api_key, model=active.model_name, api_url=active.api_url))
    return ToolAgent()


@router.post("/api/chat/tool")
async def chat_with_tool(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Chat with Function Calling tools enabled.

    Request body:
      message: str          — user question
      session_id: str       — optional, reuse conversation
      tools: list[str]      — optional, tool names to enable (default: all)
    """
    data = await request.json()
    message = data.get("message", "").strip()
    session_id = data.get("session_id", "")
    tool_names = data.get("tools")

    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    # Resolve tool schemas
    if tool_names is not None:
        from app.services.tools import all_tool_schemas
        schemas = [t for t in all_tool_schemas()
                   if t["function"]["name"] in tool_names]
        enabled_names = tool_names
    else:
        schemas = None
        enabled_names = list(registry.names())

    # Session management (persist user + assistant messages only;
    # tool intermediate messages stay inside the loop, not persisted)
    session_service = SessionService(db)
    user_id = str(user.id)
    if not session_id:
        session_id = f"{user.username}-tool-{datetime.now().timestamp()}"
    session = session_service.get_or_create_session(session_id, user_id, strict=True)
    if session is None:
        raise HTTPException(status_code=403, detail="无权访问此会话")
    session_service.add_message(session.id, str(datetime.now().timestamp()), "user", message)

    # Load recent history for context (limited to last 6 turns)
    recent = session_service.get_session_messages(session.chat_id, limit=12)
    chat_history = [{"role": m.role, "content": m.content} for m in recent]

    agent = _get_agent(db)
    answer = await agent.run(chat_history, tools=schemas)

    session_service.add_message(session.id, str(datetime.now().timestamp()), "assistant", answer)

    return {
        "response": answer,
        "session_id": session_id,
        "tools_used": enabled_names,
        "tool_trace": agent.trace,
    }


@router.get("/api/tools")
async def list_tools(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all registered agent tools with their schemas."""
    from app.services.tools.base import registry as reg
    from app.core.database import ToolDefinition

    # Load configs for dynamic tools from DB
    db_tools = {}
    try:
        rows = db.query(ToolDefinition).all()
        for r in rows:
            db_tools[r.name] = r
    except Exception:
        pass

    tools = []
    for t in reg.all_tools():
        item = {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "dynamic": bool(getattr(t, "_dynamic", False)),
        }
        if getattr(t, "_dynamic", False):
            row = db_tools.get(t.name)
            if row:
                import json as _json
                try:
                    item["config"] = _json.loads(row.config) if row.config else {}
                except Exception:
                    item["config"] = {}
            item["tool_type"] = getattr(t, "tool_type", "http")
        tools.append(item)
    return {"tools": tools}


# ── Dynamic tool management (create from UI) ──────────────────────

@router.post("/api/tools")
async def create_tool(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new dynamic tool (http / python)."""
    from app.core.database import ToolDefinition
    from app.services.tools.dynamic import register_dynamic_tool

    data = await request.json()
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    parameters = data.get("parameters") or {"type": "object", "properties": {}}
    tool_type = data.get("tool_type") or "http"
    config = data.get("config") or {}

    if not name or not description:
        raise HTTPException(status_code=400, detail="name 和 description 不能为空")
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        raise HTTPException(status_code=400, detail="工具名只能含字母/数字/下划线，且不能以数字开头")

    # uniqueness check
    exists = db.query(ToolDefinition).filter(ToolDefinition.name == name).first()
    if exists:
        raise HTTPException(status_code=400, detail=f"工具 {name} 已存在")

    import json as _json
    row = ToolDefinition(
        name=name,
        description=description,
        parameters=_json.dumps(parameters, ensure_ascii=False),
        tool_type=tool_type,
        config=_json.dumps(config, ensure_ascii=False),
        is_active=True,
        created_by=user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    ok = register_dynamic_tool(db, row)
    if not ok:
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=400, detail="工具配置无效，无法注册")

    return {"message": "工具创建成功", "id": row.id, "name": row.name}


@router.put("/api/tools/{name}")
async def update_tool(
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a dynamic tool (by name)."""
    from app.core.database import ToolDefinition
    from app.services.tools.dynamic import register_dynamic_tool, unregister_dynamic_tool

    row = db.query(ToolDefinition).filter(ToolDefinition.name == name).first()
    if not row:
        raise HTTPException(status_code=404, detail="工具不存在")

    data = await request.json()
    import json as _json
    if "name" in data and data["name"]:
        row.name = data["name"].strip()
    if "description" in data:
        row.description = data["description"].strip()
    if "parameters" in data:
        row.parameters = _json.dumps(data["parameters"], ensure_ascii=False)
    if "tool_type" in data:
        row.tool_type = data["tool_type"]
    if "config" in data:
        row.config = _json.dumps(data["config"], ensure_ascii=False)
    if "is_active" in data:
        row.is_active = bool(data["is_active"])

    db.commit()
    unregister_dynamic_tool(name)
    ok = register_dynamic_tool(db, row)
    return {"message": "工具已更新", "id": row.id, "name": row.name, "registered": ok}


@router.delete("/api/tools/{name}")
async def delete_tool(
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a dynamic tool (by name)."""
    from app.core.database import ToolDefinition
    from app.services.tools.dynamic import unregister_dynamic_tool

    row = db.query(ToolDefinition).filter(ToolDefinition.name == name).first()
    if not row:
        raise HTTPException(status_code=404, detail="工具不存在")
    unregister_dynamic_tool(name)
    db.delete(row)
    db.commit()
    return {"message": f"工具 {name} 已删除"}


@router.post("/api/tools/{name}/test")
async def test_tool(
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Test a dynamic tool with sample args (does not persist)."""
    from app.core.database import ToolDefinition
    from app.services.tools.dynamic import build_tool_from_row

    row = db.query(ToolDefinition).filter(ToolDefinition.name == name).first()
    if not row:
        raise HTTPException(status_code=404, detail="工具不存在")

    data = await request.json()
    args = data.get("args") or {}

    tool = build_tool_from_row(row.name, row.description, row.parameters,
                               row.tool_type, row.config)
    if not tool:
        raise HTTPException(status_code=400, detail="工具配置无效")

    result = await tool.execute(**args)
    return {"result": result}
