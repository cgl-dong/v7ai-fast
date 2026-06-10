"""DeepSeek AI service for chat completions."""
import httpx
from typing import Optional

from app.core.settings import settings


class DeepSeekService:
    """Service for interacting with DeepSeek API."""
    
    def __init__(self):
        self.api_key = settings.deepseek_api_key
        self.model = settings.deepseek_model
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        self.timeout = httpx.Timeout(60.0, connect=10.0)
    
    async def call_model(self, question: str, max_retries: int = 3) -> Optional[str]:
        """Call DeepSeek model with the given question, with retry on timeout."""
        if not self.api_key:
            raise RuntimeError("DeepSeek API key not configured")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.model,
            "temperature": 0.7,
            "messages": [{"role": "user", "content": question}]
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(max_retries):
                try:
                    print(f"DeepSeek attempt {attempt + 1}/{max_retries}")
                    response = await client.post(self.api_url, headers=headers, json=data)
                    response.raise_for_status()
                    
                    result = response.json()
                    if "choices" not in result:
                        raise RuntimeError("DeepSeek response format error: missing choices field")
                    
                    return result["choices"][0]["message"]["content"]
                
                except httpx.ReadTimeout:
                    print(f"DeepSeek timeout on attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        import asyncio
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    raise
                except Exception as e:
                    print(f"DeepSeek error: {e}")
                    raise
        
        return None
