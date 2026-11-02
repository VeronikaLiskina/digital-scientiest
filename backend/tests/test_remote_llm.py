import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.services import ai_publication_analysis_service as metadata
from app.services.llm import factory
from app.services.llm.base import (
    LLMAccessDeniedError,
    LLMConfigurationError,
    LLMGenerationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.services.llm.groq import GroqLLMProvider
from app.services.llm.remote_api import RemoteAPILLMProvider
from app.services.local_llm_service import RAG_ANSWER_JSON_SCHEMA


@pytest.fixture(autouse=True)
async def prepare_test_database():
    yield


def make_provider(**overrides):
    return RemoteAPILLMProvider(**{
        "base_url": "https://provider.test/v1/",
        "api_key": "test-key",
        "model": "paid-model",
        "timeout_seconds": 12,
        "max_completion_tokens": 1500,
        **overrides,
    })


def mock_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient
    sync_client = httpx.Client
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: async_client(transport=transport, **kw))
    monkeypatch.setattr(httpx, "Client", lambda **kw: sync_client(transport=transport, **kw))


async def test_api_preserves_structured_answers_without_groq_specific_fields(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": " answer "}}]})

    mock_transport(monkeypatch, respond)
    answer = await make_provider().generate(
        "question", system_prompt="rules", response_format=RAG_ANSWER_JSON_SCHEMA,
    )
    assert answer == "answer"
    request = requests[0]
    assert str(request.url) == "https://provider.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload["model"] == "paid-model"
    assert payload["max_completion_tokens"] == 1500
    assert payload["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
    ]
    assert payload["response_format"]["json_schema"]["schema"] == RAG_ANSWER_JSON_SCHEMA
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert not {"reasoning_effort", "reasoning_format", "temperature", "tools"} & payload.keys()


@pytest.mark.parametrize("sync", [False, True])
@pytest.mark.parametrize(("status", "error"), [
    (401, LLMConfigurationError), (403, LLMAccessDeniedError),
    (404, LLMConfigurationError), (429, LLMRateLimitError),
    (503, LLMUnavailableError), (400, LLMGenerationError),
    (302, LLMGenerationError),
])
async def test_api_errors_do_not_fallback(monkeypatch, sync, status, error):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "provider error"})

    mock_transport(monkeypatch, respond)
    provider = make_provider()
    with pytest.raises(error):
        if sync:
            provider.generate_sync("question", system_prompt="rules")
        else:
            await provider.generate("question", system_prompt="rules")
    assert len(calls) == 1
    assert calls[0].url.host == "provider.test"


@pytest.mark.parametrize("code", ["model_permission_blocked_org", "model_permission_blocked_project"])
async def test_explicit_model_permission_block_is_not_marked_as_transient(monkeypatch, code, caplog):
    from app.api.assistant import _assistant_http_error

    private_text = "private publication and secret-key"
    mock_transport(monkeypatch, lambda request: httpx.Response(403, json={"error": {
        "code": code, "type": "permissions_error", "message": private_text,
    }}))
    with pytest.raises(LLMConfigurationError) as caught:
        await make_provider().generate("question", system_prompt="rules")
    error = _assistant_http_error(caught.value)
    assert error.detail["retryable"] is False
    assert code in caplog.text
    assert private_text not in caplog.text
    assert private_text not in str(error.detail)


@pytest.mark.parametrize("body", [None, {"error": "Forbidden"}, {"error": {"code": "private-secret-code", "message": "private request"}}, {"error": {"code": ["unexpected"]}}])
def test_unclassified_403_allows_manual_retry_without_logging_arbitrary_body(body, caplog):
    from app.api.assistant import _assistant_http_error

    response = httpx.Response(403, json=body)
    with pytest.raises(LLMAccessDeniedError) as caught:
        make_provider()._answer(response)
    error = _assistant_http_error(caught.value)
    assert error.detail["code"] == "llm_access_denied"
    assert error.detail["retryable"] is True
    assert "provider_status=403" in caplog.text
    assert "private" not in caplog.text
    assert "unexpected" not in caplog.text


@pytest.mark.parametrize("sync", [False, True])
@pytest.mark.parametrize(("failure", "error"), [
    (httpx.ReadTimeout("slow"), LLMTimeoutError),
    (httpx.ConnectError("offline"), LLMUnavailableError),
])
async def test_api_network_errors(monkeypatch, sync, failure, error):
    def respond(request):
        raise failure

    mock_transport(monkeypatch, respond)
    with pytest.raises(error):
        if sync:
            make_provider().generate_sync("question", system_prompt="rules")
        else:
            await make_provider().generate("question", system_prompt="rules")


@pytest.mark.parametrize("body", [
    b"not json", b"null", b"{}", b'{"choices":[]}',
    b'{"choices":[{"message":{"content":" "}}]}',
    b'{"choices":[{"message":{"content":null}}]}',
])
async def test_api_rejects_unusable_answers(monkeypatch, body):
    mock_transport(monkeypatch, lambda request: httpx.Response(200, content=body))
    with pytest.raises(LLMGenerationError):
        await make_provider().generate("question", system_prompt="rules")


async def test_api_rejects_truncated_completion(monkeypatch):
    mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{
        "message": {"content": "partial answer"}, "finish_reason": "length",
    }]}))
    with pytest.raises(LLMGenerationError, match="лимитом длины"):
        await make_provider().generate("question", system_prompt="rules")


@pytest.mark.parametrize("overrides", [
    {"api_key": " "}, {"model": " "}, {"base_url": ""},
    {"base_url": "http://localhost:11434"},
    {"base_url": "https://user:password@provider.test/v1"},
])
def test_api_requires_valid_configuration(overrides):
    with pytest.raises(LLMConfigurationError):
        make_provider(**overrides)


@pytest.mark.parametrize("provider", ["ollama", "hybrid"])
def test_settings_reject_local_generation_modes(provider):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="unused", llm_provider=provider)


def test_default_is_groq_and_missing_key_does_not_fallback(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_LOCAL_FALLBACK_ENABLED", raising=False)
    config = Settings(_env_file=None, database_url="unused", groq_api_key=SecretStr(""))
    monkeypatch.setattr(factory, "settings", config)
    assert config.llm_provider == "groq"
    with pytest.raises(LLMConfigurationError, match="GROQ_API_KEY"):
        factory.create_llm_provider()
    config.groq_api_key = SecretStr("test-key")
    assert isinstance(factory.create_llm_provider(), GroqLLMProvider)


@pytest.mark.parametrize("provider", ["groq", "api"])
def test_pdf_metadata_uses_selected_api_and_analysis_timeout(monkeypatch, provider):
    config = Settings(
        _env_file=None, database_url="unused", llm_provider=provider,
        groq_api_key=SecretStr("groq-key"),
        llm_api_key=SecretStr("paid-key"),
        llm_api_base_url="https://paid.test/v1", llm_api_model="paid-model",
        ai_publication_analysis_timeout_seconds=17,
    )
    monkeypatch.setattr(factory, "settings", config)
    monkeypatch.setattr(metadata, "settings", config)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"title":"Scientific paper","authors":["Author"],"year":2025}',
        }}]})

    mock_transport(monkeypatch, respond)
    result = metadata.analyze_publication_text("Scientific paper by Author, 2025")
    assert result.title == "Scientific paper"
    assert result.authors == ["Author"]
    request = requests[0]
    payload = json.loads(request.content)
    assert payload["model"] == config.active_llm_model
    assert payload["response_format"] == {"type": "json_object"}
    assert request.extensions["timeout"]["read"] == 17
    assert request.url.host == ("api.groq.com" if provider == "groq" else "paid.test")
    assert ("reasoning_format" in payload) == (provider == "groq")
    if provider == "api":
        assert factory.create_llm_provider().model == "paid-model"


def test_optional_metadata_failure_keeps_pdf_import_available(monkeypatch):
    monkeypatch.setattr(factory.settings, "llm_provider", "groq")
    monkeypatch.setattr(factory.settings, "groq_api_key", SecretStr("test-key"))
    mock_transport(monkeypatch, lambda request: httpx.Response(429))
    assert metadata.analyze_publication_text("Scientific paper") is None


def test_disabled_metadata_does_not_create_provider(monkeypatch):
    monkeypatch.setattr(metadata.settings, "ai_publication_analysis_enabled", False)

    def fail(**kwargs):
        pytest.fail("Disabled analysis must not construct an API client")

    monkeypatch.setattr(metadata, "create_http_llm_provider", fail)
    assert metadata.analyze_publication_text("Scientific paper") is None
