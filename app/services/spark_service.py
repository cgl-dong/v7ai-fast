import os
import httpx
from typing import Optional


class SparkService:
    def __init__(self):
        self.api_url = os.getenv("AIGC_SPARK_API_URL", "http://10.250.44.82:9000/v1")
        self.api_key = os.getenv("AIGC_SPARK_API_KEY", "sk-local-001")
        self.model = os.getenv("AIGC_SPARK_MODEL", "spark")

    async def call_spark_model(self, question: str) -> Optional[str]:
        if not self.api_url or not self.api_key or not self.model:
            raise RuntimeError("Spark model configuration not properly loaded")

        url = f"{self.api_url}/chat/completions"
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
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                print(f"Response result: {result}")

                if "choices" not in result:
                    raise RuntimeError("Spark model response format error: missing choices field")

                answer = result["choices"][0]["message"]["content"]
                return answer
            except Exception as e:
                print(f"Error calling Spark model: {e}")
                raise RuntimeError(f"Failed to call Spark model: {str(e)}")
