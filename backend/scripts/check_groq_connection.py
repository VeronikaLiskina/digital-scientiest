from __future__ import annotations

import asyncio

from app.core.config import settings
from app.services.llm.base import LocalLLMError
from app.services.llm.groq import GroqLLMProvider


async def _check() -> None:
    api_key = settings.groq_api_key.get_secret_value()
    if not api_key:
        raise SystemExit(
            "GROQ_API_KEY is empty. Add a newly created key to the project .env first."
        )

    provider = GroqLLMProvider(
        api_key=api_key,
        model=settings.groq_model,
        timeout_seconds=settings.groq_timeout_seconds,
        max_completion_tokens=min(settings.groq_max_completion_tokens, 512),
        reasoning_effort=settings.groq_reasoning_effort,
        max_retries=settings.groq_max_retries,
    )
    try:
        answer = await provider.generate(
            "Одним предложением объясни, что такое субдукция.",
            system_prompt=(
                "Ты научный ассистент. Отвечай по-русски точно и кратко."
            ),
        )
    except LocalLLMError as exc:
        raise SystemExit(f"Groq connection check failed: {exc}") from exc

    print(f"Groq connection OK: model={provider.model}")
    print(answer)


def main() -> None:
    asyncio.run(_check())


if __name__ == "__main__":
    main()
