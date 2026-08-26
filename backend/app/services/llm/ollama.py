from __future__ import annotations

import httpx

from app.services.llm.base import (
    LLMGenerationError,
    LLMTimeoutError,
    LLMUnavailableError,
    ResponseFormat,
)


class OllamaLLMProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: int,
        keep_alive: str,
        num_ctx: int,
        think: bool,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout_seconds
        self.keep_alive = keep_alive
        self.num_ctx = num_ctx
        self.think = think

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str,
        response_format: ResponseFormat = None,
    ) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "options": {
                "temperature": 0.1,
                "top_p": 0.8,
                "repeat_penalty": 1.1,
                "num_ctx": self.num_ctx,
            },
        }
        if response_format is not None:
            payload["format"] = response_format

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                "Модель не успела подготовить ответ за отведённое время"
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMUnavailableError("Сервис Ollama сейчас недоступен") from exc
        except httpx.HTTPStatusError as exc:
            raise LLMGenerationError(
                f"Ollama вернула ошибку {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError("Не удалось связаться с Ollama") from exc

        try:
            data = response.json()
            answer = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMGenerationError(
                "Ollama вернула ответ в неожиданном формате"
            ) from exc

        if not isinstance(answer, str) or not answer.strip():
            raise LLMGenerationError("Модель вернула пустой ответ")
        return answer.strip()
