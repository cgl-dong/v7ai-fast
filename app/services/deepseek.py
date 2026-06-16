"""AI service for chat completions, supporting config from database."""
import asyncio
import httpx
from typing import Optional, List

from app.core.settings import settings


class AIService:
    """Service for interacting with AI models. Reads config from DB or falls back to .env."""
    
    def __init__(self, api_key: str = None, model: str = None, api_url: str = None, temperature: float = 0.7):
        self.api_key = api_key or settings.deepseek_api_key
        self.model = model or settings.deepseek_model or "deepseek-chat"
        self.api_url = self._normalize_url(api_url) if api_url else "https://api.deepseek.com/v1/chat/completions"
        self.temperature = temperature
        self.timeout = httpx.Timeout(60.0, connect=10.0)
    
    @staticmethod
    def _normalize_url(base_url: str) -> str:
        """Ensure the URL ends with /v1/chat/completions for OpenAI-compatible APIs."""
        base = base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if "/v1" not in base:
            base = base + "/v1"
        return base + "/chat/completions"
    
    async def call_model(self, question: str, max_retries: int = 3) -> str:
        """Call AI model with the given question, with retry on errors and rate limits."""
        if not self.api_key:
            raise RuntimeError("API key not configured")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [{"role": "user", "content": question}]
        }
        
        print(f"AI call: url={self.api_url}, model={self.model}")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(max_retries):
                try:
                    print(f"AI attempt {attempt + 1}/{max_retries}")
                    response = await client.post(self.api_url, headers=headers, json=data)
                    
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        wait = int(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 30)
                        print(f"Rate limited (429), waiting {wait}s before retry...")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(wait)
                            continue
                        raise RuntimeError(f"请求频率过高，已被限流(429)。请稍后再试。")
                    
                    if response.status_code == 403:
                        raise RuntimeError(f"认证失败(403)：请检查API Key是否正确，以及该Key是否有访问模型 {self.model} 的权限")
                    
                    if response.status_code == 404:
                        raise RuntimeError(f"模型未找到(404)：模型 {self.model} 不存在或API地址 {self.api_url} 不正确")
                    
                    if response.status_code >= 500:
                        print(f"Server error {response.status_code}, retrying...")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        raise RuntimeError(f"AI服务返回服务器错误({response.status_code})：{response.text[:300]}")
                    
                    response.raise_for_status()
                    
                    try:
                        result = response.json()
                    except Exception:
                        raise RuntimeError(f"AI响应不是有效的JSON。状态码={response.status_code}")
                    
                    if "choices" not in result:
                        error_msg = result.get("error", {}).get("message", str(result))
                        raise RuntimeError(f"AI返回格式错误: {error_msg}")
                    
                    return result["choices"][0]["message"]["content"]
                
                except httpx.ReadTimeout:
                    print(f"AI timeout on attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise RuntimeError("AI服务响应超时，请稍后再试。")
                
                except RuntimeError:
                    raise
                except Exception as e:
                    print(f"AI error: {e}")
                    raise RuntimeError(str(e))
        
        raise RuntimeError("AI调用失败：已达到最大重试次数")

    async def call_model_with_messages(self, messages: List[dict], temperature: float = 0.7) -> str:
        """Call AI model with a list of messages (for agent use)."""
        if not self.api_key:
            raise RuntimeError("API key not configured")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        data = {"model": self.model, "temperature": temperature, "messages": messages}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]


# Keep backward compatibility
DeepSeekService = AIService
