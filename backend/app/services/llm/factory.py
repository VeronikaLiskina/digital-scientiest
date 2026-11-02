from __future__ import annotations

from app.core.config import settings
from app.services.llm.base import LLMConfigurationError, LLMProvider
from app.services.llm.groq import GroqLLMProvider
from app.services.llm.remote_api import RemoteAPILLMProvider
from app.services.llm.fallback import FallbackLLMProvider, FallbackState
from app.services.llm.ollama import OllamaLLMProvider


_fallback_states: dict[tuple[str, str, str], FallbackState] = {}


def create_http_llm_provider(*, timeout_seconds: int | None = None) -> RemoteAPILLMProvider:
    """HTTP adapter also used by synchronous PDF metadata extraction."""
    if settings.llm_provider == "groq":
        return RemoteAPILLMProvider(
            base_url="https://api.groq.com/openai/v1",
            api_key=settings.groq_api_key.get_secret_value(),
            model=settings.groq_model,
            timeout_seconds=timeout_seconds or settings.groq_timeout_seconds,
            max_completion_tokens=settings.groq_max_completion_tokens,
            request_options={
                "temperature": 0.1,
                "reasoning_effort": settings.groq_reasoning_effort,
                "reasoning_format": "hidden",
            },
        )
    if settings.llm_provider == "api":
        return RemoteAPILLMProvider(
            base_url=settings.llm_api_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            model=settings.llm_api_model,
            timeout_seconds=timeout_seconds or settings.llm_api_timeout_seconds,
            max_completion_tokens=settings.llm_api_max_completion_tokens,
        )
    raise LLMConfigurationError("Доступны только API-провайдеры: groq и api")


def _create_groq_provider() -> GroqLLMProvider:
    return GroqLLMProvider(
        api_key=settings.groq_api_key.get_secret_value(),
        model=settings.groq_model,
        timeout_seconds=settings.groq_timeout_seconds,
        max_completion_tokens=settings.groq_max_completion_tokens,
        reasoning_effort=settings.groq_reasoning_effort,
        max_retries=settings.groq_max_retries,
    )


def _create_api_provider() -> LLMProvider:
    provider = settings.llm_provider.strip().lower()
    if provider == "groq":
        return _create_groq_provider()
    return create_http_llm_provider()


def create_local_provider() -> OllamaLLMProvider:
    return OllamaLLMProvider(
        base_url=settings.ollama_base_url, model=settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds, keep_alive=settings.ollama_keep_alive,
        num_ctx=settings.ollama_num_ctx, num_predict=settings.ollama_num_predict,
        num_thread=settings.ollama_num_thread,
        num_batch=settings.ollama_num_batch, use_mmap=settings.ollama_use_mmap,
    )


def create_llm_provider() -> LLMProvider:
    if not settings.llm_local_fallback_enabled:
        return _create_api_provider()
    key = (settings.llm_provider, settings.llm_api_base_url, settings.active_llm_model)
    return FallbackLLMProvider(
        primary=_create_api_provider, fallback=create_local_provider,
        model=settings.active_llm_model,
        api_timeout_seconds=settings.llm_fallback_api_timeout_seconds,
        cooldown_seconds=settings.llm_fallback_cooldown_seconds,
        state=_fallback_states.setdefault(key, FallbackState()),
    )
