from types import SimpleNamespace

import pytest

from app.services.llm.base import LLMConfigurationError
from app.services.llm.groq import GroqLLMProvider
from app.services.local_llm_service import (
    LocalLLMService,
    RAG_ANSWER_JSON_SCHEMA,
)


class CapturingCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content),
                )
            ]
        )


class FakeGroqClient:
    def __init__(self, content: str) -> None:
        self.completions = CapturingCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)


def make_provider(client: FakeGroqClient) -> GroqLLMProvider:
    return GroqLLMProvider(
        api_key="",
        model="openai/gpt-oss-120b",
        timeout_seconds=120,
        max_completion_tokens=4096,
        reasoning_effort="medium",
        client=client,
    )


async def test_groq_provider_preserves_rag_contract_without_external_tools():
    raw_answer = (
        '{"blocks":[{"kind":"answer","text":"Ответ по источнику.",'
        '"source_ids":["chunk-1"]}]}'
    )
    client = FakeGroqClient(raw_answer)
    service = LocalLLMService(provider=make_provider(client))

    answer = await service.generate_answer(
        "Контекст и вопрос",
        expected_language="ru",
        structured_output=True,
    )

    assert answer == raw_answer
    request = client.completions.requests[0]
    assert request["model"] == "openai/gpt-oss-120b"
    assert request["temperature"] == 0.1
    assert request["reasoning_effort"] == "medium"
    assert request["reasoning_format"] == "hidden"
    assert request["max_completion_tokens"] == 4096
    assert "tools" not in request
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "digital_scientist_response",
            "strict": True,
            "schema": RAG_ANSWER_JSON_SCHEMA,
        },
    }


async def test_groq_provider_plain_completion_has_no_response_format():
    client = FakeGroqClient("Краткий ответ.")
    provider = make_provider(client)

    answer = await provider.generate(
        "Что такое субдукция?",
        system_prompt="Отвечай кратко.",
    )

    assert answer == "Краткий ответ."
    assert "response_format" not in client.completions.requests[0]


def test_groq_provider_requires_api_key_without_injected_client():
    with pytest.raises(LLMConfigurationError, match="GROQ_API_KEY"):
        GroqLLMProvider(
            api_key="",
            model="openai/gpt-oss-120b",
            timeout_seconds=120,
            max_completion_tokens=4096,
            reasoning_effort="medium",
        )
