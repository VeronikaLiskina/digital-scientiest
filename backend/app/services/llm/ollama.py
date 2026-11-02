from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

import httpx

from app.services.llm.base import (
    LLMConfigurationError, LLMGenerationError, LLMTimeoutError, LLMUnavailableError, ResponseFormat,
)


class OllamaLLMProvider:
    """Use an installed model only. No pulls, preloads or persistent residency."""

    name = "ollama"
    _locks: WeakKeyDictionary = WeakKeyDictionary()

    def __init__(self, *, base_url: str, model: str, timeout_seconds: int = 240,
                 keep_alive: str = "0", num_ctx: int = 16384,
                 num_predict: int = 4096, num_thread: int = 2,
                 num_batch: int = 128, use_mmap: bool = True):
        if not model.strip() or not base_url.strip():
            raise LLMConfigurationError("Для локального резерва нужны адрес Ollama и имя установленной модели")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout_seconds
        self.keep_alive = keep_alive
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.num_thread = num_thread
        self.num_batch = num_batch
        self.use_mmap = use_mmap

    async def generate(self, prompt: str, *, system_prompt: str, response_format: ResponseFormat = None) -> str:
        payload = {
            "model": self.model, "stream": False, "think": False, "keep_alive": self.keep_alive,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            "options": {"temperature": 0.1, "num_ctx": self.num_ctx,
                        "num_predict": self.num_predict, "num_thread": self.num_thread,
                        # Windows CUDA defaults to a full anonymous-memory copy.
                        # Mapping the installed weights avoids that memory peak
                        # alongside retrieval models; a small batch limits scratch space.
                        "use_mmap": self.use_mmap, "num_batch": self.num_batch},
        }
        if response_format is not None:
            payload["format"] = response_format
        loop = asyncio.get_running_loop()
        lock = self._locks.setdefault(loop, asyncio.Lock())
        try:
            # Serialize local work within the backend to contain memory/CPU use.
            async with lock, httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=5), trust_env=False) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("Локальная модель не успела подготовить ответ") from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError("Не удалось подключиться к локальной Ollama") from exc
        if response.status_code == 404:
            raise LLMConfigurationError("Локальная модель не найдена в Ollama; установите указанную в настройках модель")
        if response.status_code >= 500:
            raise LLMUnavailableError(f"Ollama недоступна: HTTP {response.status_code}")
        if not 200 <= response.status_code < 300:
            raise LLMGenerationError(f"Ollama отклонила запрос: HTTP {response.status_code}")
        try:
            data = response.json()
            answer = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMGenerationError("Ollama вернула некорректный ответ") from exc
        if data.get("done_reason") == "length":
            raise LLMGenerationError("Ответ локальной модели прерван лимитом длины")
        if not isinstance(answer, str) or not answer.strip():
            raise LLMGenerationError("Локальная модель вернула пустой ответ")
        return answer.strip()
