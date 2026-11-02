"""API first, lazy local recovery; never run both generations in parallel."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from collections.abc import Callable

from app.services.llm.base import (
    LLMGenerationError, LLMProvider, LLMTimeoutError, LocalLLMError, ResponseFormat,
)

logger = logging.getLogger(__name__)


class LLMFallbackError(LocalLLMError):
    """Neither the API nor its local reserve produced a usable response."""


@dataclass
class FallbackState:
    retry_after: float = 0


class FallbackLLMProvider:
    name = "api_with_local_fallback"

    def __init__(self, *, primary: Callable[[], LLMProvider], fallback: Callable[[], LLMProvider],
                 model: str, api_timeout_seconds: float = 30, cooldown_seconds: float = 60,
                 state: FallbackState | None = None):
        self.model = model
        self._primary_factory = primary
        self._fallback_factory = fallback
        self._primary: LLMProvider | None = None
        self._fallback: LLMProvider | None = None
        self._local = False
        self.api_timeout_seconds = api_timeout_seconds
        self.cooldown_seconds = cooldown_seconds
        self.state = state if state is not None else FallbackState()

    def activate_fallback(self) -> bool:
        """Called when an otherwise successful API answer fails validation."""
        if self._local:
            return False
        self._local = True
        self.state.retry_after = time.monotonic() + self.cooldown_seconds
        return True

    @staticmethod
    def _validate(answer: str, response_format: ResponseFormat) -> str:
        if not isinstance(answer, str) or not answer.strip():
            raise LLMGenerationError("Модель вернула пустой ответ")
        if response_format is not None:
            try:
                value = json.loads(answer)
            except (ValueError, TypeError) as exc:
                raise LLMGenerationError("Модель вернула некорректный JSON") from exc
            if not isinstance(value, dict):
                raise LLMGenerationError("Модель вернула JSON без объекта ответа")
        return answer.strip()

    async def generate(self, prompt: str, *, system_prompt: str, response_format: ResponseFormat = None) -> str:
        if not self._local and time.monotonic() >= self.state.retry_after:
            try:
                if self._primary is None:
                    self._primary = self._primary_factory()
                try:
                    answer = await asyncio.wait_for(self._primary.generate(
                        prompt, system_prompt=system_prompt, response_format=response_format,
                    ), timeout=self.api_timeout_seconds)
                except TimeoutError as exc:
                    raise LLMTimeoutError("Превышено время ожидания API перед локальным резервом") from exc
                answer = self._validate(answer, response_format)
                self.state.retry_after = 0
                return answer
            except LocalLLMError as exc:
                # Never log prompts, provider response bodies or keys.
                logger.warning("Switching to local reserve: error=%s", type(exc).__name__)
                self.activate_fallback()
        else:
            self._local = True
        try:
            if self._fallback is None:
                self._fallback = self._fallback_factory()
            answer = await self._fallback.generate(prompt, system_prompt=system_prompt, response_format=response_format)
            return self._validate(answer, response_format)
        except LocalLLMError as exc:
            logger.warning("Local reserve failed: error=%s", type(exc).__name__)
            raise LLMFallbackError("API и локальная резервная модель не смогли подготовить ответ") from exc
