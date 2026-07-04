import json
import aiohttp

from src.utils.logger import logger


class OllamaClient:
    def __init__(self, host: str = "127.0.0.1:11434", model: str = "qwen2:0.5b",
                 timeout: int = 120, max_retries: int = 3):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = f"http://{self.host}/api"

    async def generate(self, prompt: str, system_prompt: str = "",
                       temperature: float = 0.3) -> str:
        url = f"{self.base_url}/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 512,
            },
        }

        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get("response", "").strip()
                        else:
                            text = await resp.text()
                            logger.warning(f"Ollama API error (attempt {attempt+1}): {resp.status} - {text[:200]}")
            except aiohttp.ClientError as e:
                logger.warning(f"Ollama connection error (attempt {attempt+1}): {e}")
            except Exception as e:
                logger.error(f"Ollama unexpected error (attempt {attempt+1}): {e}")

            if attempt < self.max_retries - 1:
                import asyncio
                await asyncio.sleep(2 ** attempt)

        return ""

    async def chat(self, messages: list[dict], temperature: float = 0.3) -> str:
        url = f"{self.base_url}/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 512,
            },
        }

        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            msg = data.get("message", {})
                            return msg.get("content", "").strip()
                        else:
                            text = await resp.text()
                            logger.warning(f"Ollama chat error: {resp.status}")
            except Exception as e:
                logger.warning(f"Ollama chat attempt {attempt+1} failed: {e}")

            if attempt < self.max_retries - 1:
                import asyncio
                await asyncio.sleep(2 ** attempt)

        return ""

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{self.base_url}/tags") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        has_model = any(self.model in m for m in models)
                        logger.info(f"Ollama health: OK, models: {models}")
                        return has_model
                    return False
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False
