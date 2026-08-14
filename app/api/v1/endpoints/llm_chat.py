"""LLM 直连对话 — 不使用 RAG，直接调用模型流式返回。"""
import json
import re
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse
from app.services.deepseek import AIService

router = APIRouter()


@router.get("/llm")
async def llm_page():
    return FileResponse("static/llm_chat.html")


@router.get("/llm/chat/stream")
async def llm_chat_stream(prompt: str):
    """SSE 流式接口：直接调用 DeepSeek 模型，不做 RAG 检索。"""
    ai = AIService()

    async def event_generator():
        yield "data: 开始生成回答\n\n"
        try:
            async for token in ai.call_model_stream(prompt):
                yield f"data: {token}\n\n"
        except Exception as e:
            yield f"data: [错误: {str(e)}]\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/llm/chat/json")
async def llm_chat_json(request: Request):
    """结构化 JSON 输出：根据 prompt + schema 强制模型返回合法 JSON。"""
    body = await request.json()
    prompt = body.get("prompt", "")
    schema = body.get("schema")

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    ai = AIService(temperature=0.0)

    # 构建 schema 描述
    schema_desc = ""
    if schema:
        try:
            schema_obj = json.loads(schema) if isinstance(schema, str) else schema
            schema_desc = json.dumps(schema_obj, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            schema_desc = str(schema)

    json_prompt = f"""{prompt}

严格要求：仅返回标准JSON，禁止任何解释、注释、markdown、多余文字。
JSON Schema 定义：
{schema_desc}

只输出符合上述 Schema 的 JSON 对象。"""

    try:
        raw = await ai.call_model(json_prompt)
        # 正则提取 JSON
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            # 重试一次
            raw = await ai.call_model(json_prompt)
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise HTTPException(status_code=500, detail="模型无法输出合法JSON")
        return json.loads(match.group())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"JSON结构化输出失败: {str(e)}")