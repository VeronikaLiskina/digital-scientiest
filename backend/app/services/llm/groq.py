from __future__ import annotations

from typing import Any

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    RateLimitError,
)

from app.services.llm.base import (
    LLMConfigurationError,
    LLMGenerationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    ResponseFormat,
)


class GroqLLMProvider:
    name = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_completion_tokens: int,
        reasoning_effort: str,
        max_retries: int = 1,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip() and client is None:
            raise LLMConfigurationError(
                "Для провайдера Groq не задан GROQ_API_KEY"
            )
        self.model = model
        self.max_completion_tokens = max_completion_tokens
        self.reasoning_effort = reasoning_effort
        self.client = client or AsyncGroq(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @staticmethod
    def _structured_response_format(schema: ResponseFormat) -> dict | None:
        if schema is None:
            return None
        if not isinstance(schema, dict):
            raise LLMGenerationError(
                "Groq structured output requires a JSON Schema object"
            )
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "digital_scientist_response",
                "strict": True,
                "schema": schema,
            },
        }

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str,
        response_format: ResponseFormat = None,
    ) -> str:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_completion_tokens": self.max_completion_tokens,
            "reasoning_effort": self.reasoning_effort,
            "reasoning_format": "hidden",
        }
        structured_format = self._structured_response_format(response_format)
        if structured_format is not None:
            request["response_format"] = structured_format

        try:
            completion = await self.client.chat.completions.create(**request)
        except RateLimitError as exc:
            raise LLMRateLimitError(
                "Лимит Groq временно исчерпан; повторите запрос позже"
            ) from exc
        except APITimeoutError as exc:
            raise LLMTimeoutError(
                "Groq не успел подготовить ответ за отведённое время"
            ) from exc
        except APIConnectionError as exc:
            raise LLMUnavailableError("Не удалось подключиться к Groq") from exc
        except APIStatusError as exc:
            detail = ""
            try:
                error_message = exc.response.json().get("error", {}).get("message")
            except (AttributeError, TypeError, ValueError):
                error_message = None
            if isinstance(error_message, str) and error_message.strip():
                detail = f": {error_message.strip()}"
            if exc.status_code in {401, 403}:
                raise LLMConfigurationError(
                    "Groq отклонил API-ключ или доступ к выбранной модели"
                    f"{detail}"
                ) from exc
            if exc.status_code >= 500:
                raise LLMUnavailableError(
                    f"Groq временно недоступен: HTTP {exc.status_code}{detail}"
                ) from exc
            raise LLMGenerationError(
                f"Groq отклонил запрос: HTTP {exc.status_code}{detail}"
            ) from exc

        try:
            answer = completion.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMGenerationError(
                "Groq вернул ответ в неожиданном формате"
            ) from exc
        if not isinstance(answer, str) or not answer.strip():
            raise LLMGenerationError("Модель вернула пустой ответ")
        return answer.strip()
