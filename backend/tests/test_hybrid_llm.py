import asyncio

import pytest

from app.services.llm.base import LLMRateLimitError, LLMUnavailableError
from app.services.llm.hybrid import HybridLLMProvider


class FakeProvider:
    def __init__(
        self,
        *,
        name: str,
        model: str,
        delay: float = 0.0,
        answer: str = "answer",
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.delay = delay
        self.answer = answer
        self.error = error
        self.calls = 0
        self.cancelled = False

    async def generate(self, prompt, *, system_prompt, response_format=None):
        self.calls += 1
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.error is not None:
            raise self.error
        return self.answer


def make_hybrid(
    primary: FakeProvider,
    fallback: FakeProvider,
    *,
    delay: float = 0.01,
) -> HybridLLMProvider:
    return HybridLLMProvider(
        primary=primary,
        fallback=fallback,
        fallback_delay_seconds=delay,
    )


async def test_fast_primary_does_not_start_fallback():
    primary = FakeProvider(name="ollama", model="gemma", answer="local")
    fallback = FakeProvider(name="groq", model="gpt-oss", answer="remote")
    provider = make_hybrid(primary, fallback)

    answer = await provider.generate("prompt", system_prompt="system")

    assert answer == "local"
    assert primary.calls == 1
    assert fallback.calls == 0
    assert provider.last_generation == {
        "winner": "primary",
        "winner_provider": "ollama",
        "winner_model": "gemma",
        "fallback_started": False,
        "fallback_reason": None,
        "fallback_delay_seconds": 0.01,
        "errors": {},
        "elapsed_sec": provider.last_generation["elapsed_sec"],
    }


async def test_slow_primary_starts_fallback_and_uses_faster_answer():
    primary = FakeProvider(
        name="ollama",
        model="gemma",
        delay=0.1,
        answer="local",
    )
    fallback = FakeProvider(
        name="groq",
        model="gpt-oss",
        delay=0.005,
        answer="remote",
    )
    provider = make_hybrid(primary, fallback)

    answer = await provider.generate("prompt", system_prompt="system")

    assert answer == "remote"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert primary.cancelled is True
    assert provider.last_generation["winner"] == "fallback"
    assert provider.last_generation["fallback_reason"] == "delay_exceeded"


async def test_fallback_error_keeps_waiting_for_in_flight_primary():
    primary = FakeProvider(
        name="ollama",
        model="gemma",
        delay=0.1,
        answer="local",
    )
    fallback = FakeProvider(
        name="groq",
        model="gpt-oss",
        delay=0.005,
        error=LLMRateLimitError("quota"),
    )
    provider = make_hybrid(primary, fallback)

    answer = await provider.generate("prompt", system_prompt="system")

    assert answer == "local"
    assert primary.cancelled is False
    assert provider.last_generation["winner"] == "primary"
    assert "LLMRateLimitError" in provider.last_generation["errors"]["fallback"]


async def test_primary_error_starts_fallback_without_waiting_for_delay():
    primary = FakeProvider(
        name="ollama",
        model="gemma",
        error=LLMUnavailableError("offline"),
    )
    fallback = FakeProvider(name="groq", model="gpt-oss", answer="remote")
    provider = make_hybrid(primary, fallback, delay=1.0)

    answer = await provider.generate("prompt", system_prompt="system")

    assert answer == "remote"
    assert provider.last_generation["winner"] == "fallback"
    assert provider.last_generation["fallback_reason"] == "primary_error"


async def test_both_provider_errors_raise_fallback_error():
    primary = FakeProvider(
        name="ollama",
        model="gemma",
        error=LLMUnavailableError("offline"),
    )
    fallback = FakeProvider(
        name="groq",
        model="gpt-oss",
        error=LLMRateLimitError("quota"),
    )
    provider = make_hybrid(primary, fallback)

    with pytest.raises(LLMRateLimitError, match="quota"):
        await provider.generate("prompt", system_prompt="system")

    assert provider.last_generation["winner"] is None
    assert set(provider.last_generation["errors"]) == {"primary", "fallback"}


def test_hybrid_delay_must_be_positive():
    primary = FakeProvider(name="ollama", model="gemma")
    fallback = FakeProvider(name="groq", model="gpt-oss")

    with pytest.raises(ValueError, match="positive"):
        make_hybrid(primary, fallback, delay=0)
