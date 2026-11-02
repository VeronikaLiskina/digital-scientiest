import pytest

from app.api import assistant
from app.dependencies import get_embedding_service
from app.main import app
from app.services.llm.base import (
    LLMAccessDeniedError,
    LLMConfigurationError,
    LLMGenerationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)


class FakeEmbeddingService:
    model_name = "fake-embedding-model"

    def embed_query(self, _text: str) -> list[float]:
        return [0.1] * 768

    def embed_text(self, _text: str) -> list[float]:
        return [0.1] * 768


async def test_general_chat_persists_origin_and_continues_without_archive_models(client, monkeypatch):
    from app.services import assistant_conversation_service

    prompts = []

    class GeneralLLM:
        async def generate_general_knowledge_answer(self, prompt, **kwargs):
            prompts.append(prompt)
            return "Привет! Давай поговорим о музыке."

    def no_search():
        pytest.fail("Conversation must not load search models")

    monkeypatch.setattr(assistant_conversation_service, "LocalLLMService", GeneralLLM)
    monkeypatch.setattr(assistant, "get_embedding_service", no_search)
    chat_id = (await client.post("/assistant/chats", json={})).json()["id"]
    for content in ["Привет", "А расскажи ещё"]:
        response = await client.post(f"/assistant/chats/{chat_id}/messages", json={"content": content})
        assert response.status_code == 200, response.text
        message = response.json()["assistant_message"]
        assert message["answer_origin"] == "external"
        assert message["sources"] == []
        assert message["catalog"] is None
    assert "Пользователь: Привет" in prompts[-1]
    saved = (await client.get(f"/assistant/chats/{chat_id}")).json()["messages"]
    assert [message["answer_origin"] for message in saved if message["role"] == "assistant"] == ["external", "external"]


async def test_unknown_answer_mode_is_rejected(client):
    response = await client.post("/assistant/ask", json={"question": "Привет", "mode": "unknown"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_history_create_send_reopen_and_delete(client, monkeypatch):
    conversations: list[str | None] = []

    async def fake_answer_question(**kwargs):
        conversations.append(kwargs.get("conversation"))
        return {
            "question": kwargs["question"],
            "answer": f"Ответ: {kwargs['question']}",
            "sources": [],
            "answer_blocks": [
                {"text": f"Ответ: {kwargs['question']}", "source_ids": []}
            ],
            "answer_origin": "external",
            "catalog": None,
        }

    monkeypatch.setattr(assistant, "_answer_question", fake_answer_question)
    app.dependency_overrides[get_embedding_service] = lambda: FakeEmbeddingService()

    created = await client.post("/assistant/chats", json={})
    assert created.status_code == 201
    chat_id = created.json()["id"]
    assert created.json()["title"] == "Новый чат"

    first = await client.post(
        f"/assistant/chats/{chat_id}/messages",
        json={"content": "Что такое магматизм?"},
    )
    assert first.status_code == 200
    assert first.json()["chat"]["title"] == "Что такое магматизм?"
    assert first.json()["user_message"]["role"] == "user"
    assert first.json()["assistant_message"]["role"] == "assistant"
    assert first.json()["assistant_message"]["answer_origin"] == "external"
    assert conversations[0] == ""

    second = await client.post(
        f"/assistant/chats/{chat_id}/messages",
        json={"content": "А где это встречается?"},
    )
    assert second.status_code == 200
    assert "Пользователь: Что такое магматизм?" in conversations[1]
    assert "Ассистент: Ответ: Что такое магматизм?" in conversations[1]

    detail = await client.get(f"/assistant/chats/{chat_id}")
    assert detail.status_code == 200
    assert [message["role"] for message in detail.json()["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]

    chats = await client.get("/assistant/chats")
    assert chats.status_code == 200
    assert [chat["id"] for chat in chats.json()] == [chat_id]

    deleted = await client.delete(f"/assistant/chats/{chat_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/assistant/chats/{chat_id}")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "error",
        "expected_status",
        "expected_code",
        "expected_title",
        "expected_retryable",
    ),
    [
        (
            LLMUnavailableError("offline"),
            503,
            "llm_unavailable",
            "Ассистент временно недоступен",
            True,
        ),
        (
            LLMTimeoutError("slow"),
            504,
            "llm_timeout",
            "Ответ занял слишком много времени",
            True,
        ),
        (
            LLMGenerationError("invalid response"),
            502,
            "generation_failed",
            "Не удалось подготовить ответ",
            True,
        ),
        (
            LLMRateLimitError("quota"),
            429,
            "llm_rate_limited",
            "Временный лимит запросов",
            True,
        ),
        (
            LLMConfigurationError("missing key"),
            503,
            "llm_configuration_error",
            "Нет доступа к модели",
            False,
        ),
        (
            LLMAccessDeniedError("forbidden"),
            503,
            "llm_access_denied",
            "Сервис модели отклонил запрос",
            True,
        ),
    ],
)
async def test_chat_returns_clear_recoverable_model_errors(
    client,
    monkeypatch,
    error,
    expected_status,
    expected_code,
    expected_title,
    expected_retryable,
):
    async def failing_answer_question(**_kwargs):
        raise error

    monkeypatch.setattr(assistant, "_answer_question", failing_answer_question)
    app.dependency_overrides[get_embedding_service] = lambda: FakeEmbeddingService()

    created = await client.post("/assistant/chats", json={})
    chat_id = created.json()["id"]
    response = await client.post(
        f"/assistant/chats/{chat_id}/messages",
        json={"content": "Расскажите о Байкале"},
    )

    assert response.status_code == expected_status
    detail = response.json()["detail"]
    assert detail["code"] == expected_code
    assert detail["title"] == expected_title
    assert detail["retryable"] is expected_retryable
    assert isinstance(detail["message"], str) and detail["message"]
    assert "Traceback" not in response.text

    # A failed exchange is rolled back, so retrying does not duplicate the question.
    saved_chat = await client.get(f"/assistant/chats/{chat_id}")
    assert saved_chat.json()["messages"] == []
