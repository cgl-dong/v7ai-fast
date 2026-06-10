import os
import httpx
from typing import Optional


class DeepSeekService:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.api_url = "https://api.deepseek.com/v1/chat/completions"

    async def call_deepseek_model(self, question: str) -> Optional[str]:
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

        print(f"Request params: {data}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.api_url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                print(f"Response result: {result}")

                if "choices" not in result:
                    raise RuntimeError("DeepSeek response format error: missing choices field")

                answer = result["choices"][0]["message"]["content"]
                return answer
            except Exception as e:
                print(f"Error calling DeepSeek model: {e}")
                raise RuntimeError(f"Failed to call DeepSeek model: {str(e)}")
