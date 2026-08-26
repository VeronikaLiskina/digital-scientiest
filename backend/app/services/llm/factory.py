from __future__ import annotations

from app.core.config import settings
from app.services.llm.base import LLMConfigurationError, LLMProvider
from app.services.llm.groq import GroqLLMProvider
from app.services.llm.hybrid import HybridLLMProvider
from app.services.llm.ollama import OllamaLLMProvider


def _create_ollama_provider() -> OllamaLLMProvider:
    return OllamaLLMProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
        keep_alive=settings.ollama_keep_alive,
        num_ctx=settings.ollama_num_ctx,
        think=settings.ollama_think,
    )


def _create_groq_provider() -> GroqLLMProvider:
    return GroqLLMProvider(
        api_key=settings.groq_api_key.get_secret_value(),
        model=settings.groq_model,
        timeout_seconds=settings.groq_timeout_seconds,
        max_completion_tokens=settings.groq_max_completion_tokens,
        reasoning_effort=settings.groq_reasoning_effort,
        max_retries=settings.groq_max_retries,
    )


def create_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.strip().lower()
    if provider == "ollama":
        return _create_ollama_provider()
    if provider == "groq":
        return _create_groq_provider()
    if provider == "hybrid":
        return HybridLLMProvider(
            primary=_create_ollama_provider(),
            fallback=_create_groq_provider(),
            fallback_delay_seconds=settings.hybrid_fallback_delay_seconds,
        )
    raise LLMConfigurationError(
        f"Неизвестный LLM_PROVIDER={settings.llm_provider!r}; "
        "допустимы ollama, groq и hybrid"
    )
