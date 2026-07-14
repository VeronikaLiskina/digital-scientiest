import pytest

from app.api import assistant
from app.dependencies import get_embedding_service
from app.main import app


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
