import asyncio
import json

import httpx
import pytest

from app.api.assistant import _assistant_http_error
from app.services.assistant_generation_service import AssistantGenerationService
from app.services.llm.base import (
    LLMAccessDeniedError, LLMConfigurationError, LLMGenerationError,
    LLMRateLimitError, LLMTimeoutError, LLMUnavailableError,
)
from app.services.llm.fallback import FallbackLLMProvider, FallbackState, LLMFallbackError
from app.services.llm.ollama import OllamaLLMProvider
from app.services.local_llm_service import LocalLLMService, RAG_SYSTEM_PROMPT


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


class Stub:
    name = "stub"
    model = "test"

    def __init__(self, result):
        self.result = result
        self.calls = []

    async def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def wrapper(primary, local, **options):
    return FallbackLLMProvider(primary=lambda: primary, fallback=lambda: local, model="API", **options)


async def test_api_success_does_not_even_construct_local_provider():
    def forbidden():
        pytest.fail("Local reserve must stay unloaded while API works")

    provider = FallbackLLMProvider(primary=lambda: Stub("API answer"), fallback=forbidden, model="API")
    assert await provider.generate("question", system_prompt="rules") == "API answer"


@pytest.mark.parametrize("error", [
    LLMAccessDeniedError, LLMConfigurationError, LLMRateLimitError,
    LLMUnavailableError, LLMTimeoutError, LLMGenerationError,
])
async def test_provider_failure_uses_local_with_identical_prompt_and_schema(error, caplog):
    primary = Stub(error("private-provider-message"))
    local = Stub('{"query":"answer"}')
    provider = wrapper(primary, local)
    schema = {"type": "object"}
    result = await provider.generate("question with sources", system_prompt="strict rules", response_format=schema)
    assert json.loads(result) == {"query": "answer"}
    assert primary.calls == local.calls
    assert "private-provider-message" not in caplog.text


async def test_missing_api_configuration_also_falls_back_lazily():
    def missing():
        raise LLMConfigurationError("missing key")

    provider = FallbackLLMProvider(primary=missing, fallback=lambda: Stub("local"), model="API")
    assert await provider.generate("question", system_prompt="rules") == "local"


async def test_deadline_cancels_api_before_starting_local():
    order = []

    class Slow(Stub):
        async def generate(self, *args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                order.append("API cancelled")

    class Local(Stub):
        async def generate(self, *args, **kwargs):
            order.append("local started")
            return "local"

    provider = wrapper(Slow(None), Local(None), api_timeout_seconds=.01)
    assert await provider.generate("question", system_prompt="rules") == "local"
    assert order == ["API cancelled", "local started"]


@pytest.mark.parametrize("answer", ["", " ", "not JSON", "[]"])
async def test_empty_or_broken_structured_output_falls_back(answer):
    local = Stub('{"query":"valid"}')
    provider = wrapper(Stub(answer), local)
    assert json.loads(await provider.generate("Q", system_prompt="rules", response_format={"type": "object"})) == {"query": "valid"}
    assert len(local.calls) == 1


async def test_cooldown_skips_broken_api_then_returns_to_api():
    state = FallbackState()
    primary = Stub(LLMUnavailableError("offline"))
    local = Stub("local")
    await wrapper(primary, local, state=state).generate("Q", system_prompt="rules")
    primary.result = "recovered"
    assert await wrapper(primary, local, state=state).generate("Q", system_prompt="rules") == "local"
    assert len(primary.calls) == 1
    state.retry_after = 0
    assert await wrapper(primary, local, state=state).generate("Q", system_prompt="rules") == "recovered"


async def test_cancelling_request_does_not_start_local_generation():
    started = asyncio.Event()

    class Slow(Stub):
        async def generate(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()

    local = Stub("local")
    task = asyncio.create_task(wrapper(Slow(None), local).generate("Q", system_prompt="rules"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not local.calls


async def test_both_providers_fail_with_actionable_safe_error():
    with pytest.raises(LLMFallbackError) as error:
        await wrapper(Stub(LLMUnavailableError("private")), Stub(LLMTimeoutError("private"))).generate("Q", system_prompt="rules")
    response = _assistant_http_error(error.value)
    assert response.detail["code"] == "llm_fallback_failed"
    assert response.detail["retryable"] is True
    assert "private" not in str(response.detail)


CHUNK = {"chunk_id": 1, "publication_id": 55, "publication_title": "Collection", "chunk_index": 0,
         "similarity": .9, "text": "Комиссия создана 18 декабря 1957 года."}


async def test_invalid_api_citations_use_local_after_repair_and_keep_source_validation():
    primary = Stub('{"blocks":[{"kind":"answer","text":"Ответ.","source_ids":["chunk-999"]}]}')
    local = Stub('{"blocks":[{"kind":"answer","text":"Комиссия создана 18 декабря 1957 года.","source_ids":["chunk-1"]}]}')
    service = LocalLLMService(provider=wrapper(primary, local))
    result = await AssistantGenerationService(service).generate(
        question="Когда создана комиссия?", expected_language="ru", chunks=[CHUNK], conversation=None, detail_percent=100,
    )
    assert len(primary.calls) == 2
    assert len(local.calls) == 1
    assert local.calls[0][1]["system_prompt"] == RAG_SYSTEM_PROMPT
    assert [s["chunk_id"] for s in result["sources"]] == [1]


async def test_insufficient_evidence_is_not_a_provider_failure():
    primary = Stub('{"blocks":[{"kind":"insufficient","text":"Недостаточно информации.","source_ids":[]}]}')
    local = Stub("should not run")
    result = await AssistantGenerationService(LocalLLMService(provider=wrapper(primary, local))).generate(
        question="Вопрос?", expected_language="ru", chunks=[CHUNK], conversation=None, detail_percent=100,
    )
    assert result["sources"] == []
    assert not local.calls


async def test_invalid_search_query_field_recovers_locally():
    primary, local = Stub('{"query":null}'), Stub('{"query":"Translated query"}')
    service = LocalLLMService(provider=wrapper(primary, local))
    assert await service.translate_search_query("Вопрос", source_language="ru") == "Translated query"
    assert len(primary.calls) == len(local.calls) == 1


async def test_invalid_local_citations_are_rejected_without_infinite_retries():
    bad = '{"blocks":[{"kind":"answer","text":"Ответ.","source_ids":["chunk-999"]}]}'
    primary, local = Stub(bad), Stub(bad)
    with pytest.raises(LLMGenerationError):
        await AssistantGenerationService(LocalLLMService(provider=wrapper(primary, local))).generate(
            question="Вопрос?", expected_language="ru", chunks=[CHUNK], conversation=None, detail_percent=100,
        )
    assert len(primary.calls) == 2
    assert len(local.calls) == 2


async def test_ollama_payload_uses_existing_model_and_unloads_after_generation(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": "Локальный ответ"}, "done": True})

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    provider = OllamaLLMProvider(base_url="http://ollama.test:11434", model="installed-model")
    assert await provider.generate("sources and question", system_prompt="strict rules", response_format={"type": "object"}) == "Локальный ответ"
    assert len(requests) == 1
    assert requests[0].url.path == "/api/chat"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "installed-model"
    assert payload["keep_alive"] == "0"
    assert payload["think"] is False
    assert payload["format"] == {"type": "object"}
    assert payload["options"]["num_thread"] == 2
    assert payload["options"]["num_batch"] == 128
    assert payload["options"]["use_mmap"] is True


@pytest.mark.parametrize(("status", "body", "error"), [
    (404, {"error": "private"}, LLMConfigurationError),
    (500, {"error": "private"}, LLMUnavailableError),
    (200, {"message": {"content": ""}}, LLMGenerationError),
    (200, {"message": {"content": "partial"}, "done_reason": "length"}, LLMGenerationError),
])
async def test_ollama_errors_do_not_leak_bodies_or_pull_models(monkeypatch, status, body, error):
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)), **kwargs))
    with pytest.raises(error) as exc:
        await OllamaLLMProvider(base_url="http://ollama.test", model="model").generate("Q", system_prompt="rules")
    assert "private" not in str(exc.value)
