from __future__ import annotations

from typing import Any, Protocol


ResponseFormat = str | dict[str, Any] | None


class LocalLLMError(RuntimeError):
    """Base error for failures that can be safely shown by the assistant API."""


class LLMConfigurationError(LocalLLMError):
    """The selected provider is missing required configuration."""


class LLMUnavailableError(LocalLLMError):
    """The selected provider cannot be reached."""


class LLMRateLimitError(LocalLLMError):
    """The selected provider rejected the request because of a quota limit."""


class LLMTimeoutError(LocalLLMError):
    """The selected provider did not finish generation in time."""


class LLMGenerationError(LocalLLMError):
    """The provider responded, but a usable answer could not be generated."""


class LLMProvider(Protocol):
    model: str
    name: str

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str,
        response_format: ResponseFormat = None,
    ) -> str:
        """Generate one completion without adding retrieval or external tools."""
