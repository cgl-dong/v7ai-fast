"""Tool Agent — Function Calling execution loop (Day2 integration).

Implements the standard 4-step tool calling closed loop:
  1. user question + tool list → LLM
  2. LLM decides: natural answer OR tool_calls (name + arguments)
  3. parse & validate args (Pydantic JSON Schema), execute tool
  4. feed tool result back as role="tool", re-request LLM

Safety rails (from Day2 notes):
  - max_tool_round: prevents infinite tool-call loops
  - Pydantic-style arg validation: bad args rejected and fed back
  - exception capture: tool errors returned as text, never crash the loop
"""
import json
import logging
from typing import List, Dict, Optional

from pydantic import BaseModel, ValidationError, create_model

from app.services.deepseek import AIService
from app.services.tools.base import registry
from app.services.tools import all_tool_schemas

logger = logging.getLogger(__name__)


def _build_validator(parameters: Dict) -> Optional[BaseModel]:
    """Build a Pydantic model from a JSON Schema 'properties' dict.
    Returns None if no properties (tool takes no args).
    """
    props = (parameters or {}).get("properties", {})
    if not props:
        return None
    required = set((parameters or {}).get("required", []))
    fields = {}
    for name, spec in props.items():
        ptype = spec.get("type", "string")
        pytype = {
            "string": str, "number": float, "integer": int,
            "boolean": bool, "object": dict, "array": list,
        }.get(ptype, str)
        default = ... if name in required else None
        fields[name] = (Optional[pytype] if default is None else pytype, default)
    return create_model("ToolArgs", **fields)


class ToolAgent:
    """Agent that can call registered tools in a loop until final answer."""

    def __init__(self, ai_service: Optional[AIService] = None,
                 max_tool_round: int = 3, system_prompt: Optional[str] = None):
        self.ai = ai_service or AIService()
        self.max_tool_round = max_tool_round
        self.system_prompt = system_prompt or (
            "你是一个智能助手，可以调用工具来解决问题。"
            "当需要实时信息、数学计算等工具能力时，优先调用工具；"
            "没有合适的工具时，直接用你的知识回答。"
        )
        self.trace: List[Dict] = []  # tool call trace for observability/UI

    def _prepare_messages(self, messages: List[Dict]) -> List[Dict]:
        """Ensure system prompt is first."""
        msgs = list(messages)
        if not msgs or msgs[0].get("role") != "system":
            msgs.insert(0, {"role": "system", "content": self.system_prompt})
        return msgs

    async def _execute_one_call(self, tool_call: Dict, messages: List[Dict]) -> None:
        """Parse, validate and execute one tool call; append tool result msg."""
        func_name = tool_call.get("function", {}).get("name", "")
        func_args = tool_call.get("function", {}).get("arguments", "{}")
        call_id = tool_call.get("id", "")

        # 1. Parse JSON arguments
        try:
            args_dict = json.loads(func_args) if func_args else {}
            logger.info("  ① 解析参数 JSON → %s", args_dict)
        except json.JSONDecodeError:
            err = f"工具参数解析失败，原始参数：{func_args}"
            logger.warning("  ❌ 参数解析失败: %s", func_args)
            messages.append({"role": "tool", "tool_call_id": call_id, "content": err})
            return

        # 2. Validate against tool schema (Pydantic)
        tool = registry.get(func_name)
        if tool is None:
            logger.warning("  ❌ 工具 '%s' 不存在", func_name)
            messages.append({"role": "tool", "tool_call_id": call_id,
                             "content": f"错误：不存在工具 {func_name}"})
            return

        validator = _build_validator(tool.parameters)
        if validator is not None:
            try:
                validated = validator(**args_dict)
                kwargs = validated.model_dump(exclude_none=True)
                logger.info("  ② 参数校验通过 → %s", kwargs)
            except ValidationError as ve:
                err = f"工具参数校验失败：{'; '.join(e['msg'] for e in ve.errors())}，请修正参数后重试"
                logger.warning("  ❌ 参数校验失败: %s", err[:100])
                messages.append({"role": "tool", "tool_call_id": call_id, "content": err})
                return
        else:
            kwargs = args_dict

        # 3. Execute (errors captured inside tools, but guard anyway)
        logger.info("  ③ 执行工具 '%s' 参数=%s ...", func_name, kwargs)
        try:
            exec_res = await tool.execute(**kwargs)
        except Exception as e:
            logger.error(f"[tool:{func_name}] execute error: {e}")
            exec_res = f"工具执行异常：{str(e)}"

        # 4. Feed back tool result
        result_text = str(exec_res)[:2000]
        logger.info("  ④ 工具返回结果: %s", result_text[:100])
        messages.append({"role": "tool", "tool_call_id": call_id, "content": result_text})
        logger.info("  ⑤ 结果已回填为 tool 消息，准备下一轮 LLM 调用")
        logger.info("  ────────────────────────────")

        # Record trace for observability/UI
        self.trace.append({
            "tool": func_name,
            "args": args_dict,
            "result": result_text,
        })

    async def run(self, messages: List[Dict], tools: Optional[List[Dict]] = None) -> str:
        """Main entry: run the tool-calling loop until final natural answer.

        Args:
            messages: conversation history (role/content dicts)
            tools: OpenAI tools array; defaults to all registered tools
        Returns:
            final answer text
        """
        msgs = self._prepare_messages(messages)
        tool_defs = tools if tools is not None else all_tool_schemas()
        self.trace = []  # reset trace per run

        logger.info("=" * 60)
        logger.info("🔧 [工具调用流程开始] 用户消息: %s", msgs[-1].get("content", "")[:100])
        tool_names = [t["function"]["name"] for t in tool_defs] if tool_defs else []
        logger.info("📋 [可用工具] %s", tool_names)
        logger.info("=" * 60)

        for round_no in range(1, self.max_tool_round + 1):
            logger.info("── 第 %d 轮：把消息列表(%d条)发给 LLM（带工具定义）──",
                        round_no, len(msgs))
            msg = await self.ai.call_model_with_tools(msgs, tool_defs)

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                content = msg.get("content") or "（模型未返回内容）"
                logger.info("💬 [LLM 判断] 不需要调用工具，直接回答：%s", content[:100])
                return content

            # LLM wants to call tools
            for tc in tool_calls:
                fn = tc.get("function", {}).get("name", "")
                args = tc.get("function", {}).get("arguments", "{}")
                logger.info("🎯 [LLM 判断] 选择工具 '%s'，参数: %s", fn, args[:120])

            # Append the assistant message once (carries all tool_calls),
            # then execute each call and feed results back (serial for now)
            msgs.append(msg)
            for tc in tool_calls:
                await self._execute_one_call(tc, msgs)

        # Loop exhausted: force a final answer without more tool calls
        logger.warning("[tool-agent] 达到最大轮次 %d，强制生成最终回答", self.max_tool_round)
        final = await self.ai.call_model(msgs[-1]["content"] if msgs else "请回答")
        return final
