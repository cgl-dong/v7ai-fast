"""企查查公司信息查询工具 — 调用内部 QCC API 查询企业工商信息。"""
import json
import logging
import httpx
from app.services.tools.base import BaseTool

logger = logging.getLogger(__name__)

QCC_API_BASE = "http://10.12.33.112:8079/api/qcc"


class QccTool(BaseTool):
    """企查查公司信息查询。"""

    name = "qcc_search"
    description = (
        "查询企业工商信息，如公司名称、法人代表、注册资本、成立日期、"
        "经营范围、注册地址、经营状态等。"
        "当用户询问某家公司的基本信息、工商数据时使用。"
        "参数 keyword 为公司名称关键词，支持模糊匹配。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "公司名称关键词，例如：腾讯、阿里巴巴"},
        },
        "required": ["keyword"],
    }

    async def execute(self, keyword: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.get(
                    f"{QCC_API_BASE}/getOperate",
                    params={"keyword": keyword},
                )
            if resp.status_code != 200:
                logger.error(f"[qcc] HTTP {resp.status_code}: {resp.text[:200]}")
                return f"企查查接口返回异常：HTTP {resp.status_code}"

            data = resp.json()
            # 返回格式化 JSON（最多 3000 字符，避免 token 爆炸）
            return json.dumps(data, ensure_ascii=False, indent=2)[:3000]
        except httpx.TimeoutException:
            return "企查查接口请求超时，请稍后重试"
        except Exception as e:
            logger.error(f"[qcc] execute error: {e}")
            return f"企查查查询失败：{str(e)}"


qcc_tool = QccTool()