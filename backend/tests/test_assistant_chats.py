import pytest

from app.api import assistant
from app.dependencies import get_embedding_service
from app.main import app
from app.services.local_llm_service import (
    OllamaGenerationError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


class FakeEmbeddingService:
    def embed_text(self, _text: str) -> list[float]:
        return [0.1] * 768


@pytest.mark.asyncio
async def test_chat_history_create_send_reopen_and_delete(client, monkeypatch):
    conversations: list[str | None] = []

    async def fake_answer_question(**kwargs):
        conversations.append(kwargs.get("conversation"))
        return {
            "question": kwargs["question"],
            "answer": f"Ответ: {kwargs['question']}",
            "sources": [],
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
    ("error", "expected_status", "expected_code", "expected_title"),
    [
        (
            OllamaUnavailableError("offline"),
            503,
            "ollama_unavailable",
            "Ассистент временно недоступен",
        ),
        (
            OllamaTimeoutError("slow"),
            504,
            "ollama_timeout",
            "Ответ занял слишком много времени",
        ),
        (
            OllamaGenerationError("invalid response"),
            502,
            "generation_failed",
            "Не удалось подготовить ответ",
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
    assert detail["retryable"] is True
    assert isinstance(detail["message"], str) and detail["message"]
    assert "Traceback" not in response.text

    # A failed exchange is rolled back, so retrying does not duplicate the question.
    saved_chat = await client.get(f"/assistant/chats/{chat_id}")
    assert saved_chat.json()["messages"] == []
