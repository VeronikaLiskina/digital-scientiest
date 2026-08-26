from __future__ import annotations

import asyncio
import time
from typing import Any

from app.services.llm.base import LLMProvider, ResponseFormat


class HybridLLMProvider:
    """Prefer the local model and hedge unusually slow requests through Groq."""

    name = "hybrid"

    def __init__(
        self,
        *,
        primary: LLMProvider,
        fallback: LLMProvider,
        fallback_delay_seconds: float,
    ) -> None:
        if fallback_delay_seconds <= 0:
            raise ValueError("fallback_delay_seconds must be positive")
        self.primary = primary
        self.fallback = fallback
        self.fallback_delay_seconds = fallback_delay_seconds
        self.model = f"{primary.model} + {fallback.model}"
        self._last_generation: dict[str, Any] | None = None

    @property
    def last_generation(self) -> dict[str, Any] | None:
        if self._last_generation is None:
            return None
        return dict(self._last_generation)

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str,
        response_format: ResponseFormat = None,
    ) -> str:
        started = time.perf_counter()
        primary_task = asyncio.create_task(
            self.primary.generate(
                prompt,
                system_prompt=system_prompt,
                response_format=response_format,
            )
        )
        fallback_reason: str | None = None
        errors: dict[str, Exception] = {}

        done, _ = await asyncio.wait(
            {primary_task},
            timeout=self.fallback_delay_seconds,
        )
        if primary_task in done:
            try:
                answer = primary_task.result()
            except Exception as exc:
                errors["primary"] = exc
                fallback_reason = "primary_error"
            else:
                self._record_generation(
                    winner="primary",
                    fallback_started=False,
                    fallback_reason=None,
                    started=started,
                    errors=errors,
                )
                return answer
        else:
            fallback_reason = "delay_exceeded"

        fallback_task = asyncio.create_task(
            self.fallback.generate(
                prompt,
                system_prompt=system_prompt,
                response_format=response_format,
            )
        )
        tasks: dict[asyncio.Task[str], str] = {fallback_task: "fallback"}
        if not primary_task.done():
            tasks[primary_task] = "primary"

        while tasks:
            completed, _ = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in completed:
                provider_role = tasks.pop(task)
                try:
                    answer = task.result()
                except Exception as exc:
                    errors[provider_role] = exc
                    continue

                pending = list(tasks)
                for pending_task in pending:
                    pending_task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                self._record_generation(
                    winner=provider_role,
                    fallback_started=True,
                    fallback_reason=fallback_reason,
                    started=started,
                    errors=errors,
                )
                return answer

        self._record_generation(
            winner=None,
            fallback_started=True,
            fallback_reason=fallback_reason,
            started=started,
            errors=errors,
        )
        final_error = errors.get("fallback") or errors["primary"]
        primary_error = errors.get("primary")
        if primary_error is not None and final_error is not primary_error:
            raise final_error from primary_error
        raise final_error

    def _record_generation(
        self,
        *,
        winner: str | None,
        fallback_started: bool,
        fallback_reason: str | None,
        started: float,
        errors: dict[str, Exception],
    ) -> None:
        winner_provider = None
        winner_model = None
        if winner == "primary":
            winner_provider = self.primary.name
            winner_model = self.primary.model
        elif winner == "fallback":
            winner_provider = self.fallback.name
            winner_model = self.fallback.model
        self._last_generation = {
            "winner": winner,
            "winner_provider": winner_provider,
            "winner_model": winner_model,
            "fallback_started": fallback_started,
            "fallback_reason": fallback_reason,
            "fallback_delay_seconds": self.fallback_delay_seconds,
            "errors": {
                role: f"{type(exc).__name__}: {exc}"
                for role, exc in errors.items()
            },
            "elapsed_sec": round(time.perf_counter() - started, 4),
        }
