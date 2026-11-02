from __future__ import annotations

from typing import Any

import httpx
from app.services.llm.access_errors import provider_access_error

from app.services.llm.base import (
    LLMConfigurationError,
    LLMGenerationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    ResponseFormat,
)


class RemoteAPILLMProvider:
    """Chat Completions API; never starts or falls back to a local model."""

    name = "api"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_completion_tokens: int,
        request_options: dict[str, Any] | None = None,
    ) -> None:
        if not api_key.strip() or not model.strip():
            raise LLMConfigurationError("Для API модели необходимы ключ и имя модели")
        try:
            url = httpx.URL(base_url.strip())
        except httpx.InvalidURL as exc:
            raise LLMConfigurationError("Некорректный LLM_API_BASE_URL") from exc
        if url.scheme != "https" or not url.host or url.userinfo or url.query or url.fragment:
            raise LLMConfigurationError("LLM_API_BASE_URL должен быть HTTPS-адресом API")
        self.url = f"{str(url).rstrip('/')}/chat/completions"
        self.headers = {"Authorization": f"Bearer {api_key.strip()}"}
        self.model = model.strip()
        self.timeout = timeout_seconds
        self.max_completion_tokens = max_completion_tokens
        self.request_options = request_options or {}

    def _payload(self, prompt: str, system_prompt: str, response_format: ResponseFormat) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": self.max_completion_tokens,
            **self.request_options,
        }
        if isinstance(response_format, dict):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "digital_scientist_response",
                    "strict": True,
                    "schema": response_format,
                },
            }
        elif response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        elif response_format is not None:
            raise LLMGenerationError("Неподдерживаемый формат ответа API")
        return payload

    @staticmethod
    def _answer(response: httpx.Response) -> str:
        status = response.status_code
        if status in {401, 403, 404}:
            raise provider_access_error(response)
        if status == 429:
            raise LLMRateLimitError("Лимит API временно исчерпан; повторите запрос позже")
        if status >= 500:
            raise LLMUnavailableError(f"API модели временно недоступен: HTTP {status}")
        if not 200 <= status < 300:
            raise LLMGenerationError(f"API модели отклонил запрос: HTTP {status}")
        try:
            choice = response.json()["choices"][0]
            answer = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMGenerationError("API модели вернул некорректный ответ") from exc
        if choice.get("finish_reason") == "length":
            raise LLMGenerationError("Ответ модели прерван лимитом длины; сократи ответ и заверши JSON")
        if not isinstance(answer, str) or not answer.strip():
            raise LLMGenerationError("Модель вернула пустой ответ")
        return answer.strip()

    async def generate(
        self, prompt: str, *, system_prompt: str, response_format: ResponseFormat = None,
    ) -> str:
        payload = self._payload(prompt, system_prompt, response_format)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, headers=self.headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("API модели не ответил за отведённое время") from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError("Не удалось подключиться к API модели") from exc
        return self._answer(response)

    def generate_sync(
        self, prompt: str, *, system_prompt: str, response_format: ResponseFormat = None,
    ) -> str:
        payload = self._payload(prompt, system_prompt, response_format)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self.url, headers=self.headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("API модели не ответил за отведённое время") from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError("Не удалось подключиться к API модели") from exc
        return self._answer(response)
