import pytest

from app.api import assistant
from app.services.publication_query_service import is_publication_count_question


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("RAG services must not be used for publication count questions")


async def _create_publications(client, count: int) -> None:
    for index in range(count):
        response = await client.post(
            "/api/publications",
            json={
                "title": f"Тестовая публикация {index + 1}",
                "author_ids": [],
                "topic_ids": [],
                "keyword_ids": [],
            },
        )
        assert response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Сколько статей?",
        "Сколько статей в системе?",
        "Сколько публикаций загружено?",
        "Какое количество статей есть в базе?",
    ],
)
async def test_publication_count_questions_use_database_without_rag(
    client,
    monkeypatch,
    question,
):
    await _create_publications(client, 3)
    monkeypatch.setattr(assistant, "get_embedding_service", _fail_if_called)
    monkeypatch.setattr(assistant, "LocalLLMService", _fail_if_called)
    monkeypatch.setattr(assistant, "SemanticSearchRepository", _fail_if_called)

    response = await client.post("/assistant/ask", json={"question": question})

    assert response.status_code == 200
    answer = (
        "В системе загружено 3 публикации. "
        "Информация получена из внутренней базы системы."
    )
    assert response.json() == {
        "question": question,
        "answer": answer,
        "sources": [],
        "answer_blocks": [{"text": answer, "source_ids": []}],
        "answer_origin": "internal",
        "catalog": None,
    }


@pytest.mark.asyncio
async def test_publication_count_question_returns_zero_for_empty_database(
    client,
    monkeypatch,
):
    monkeypatch.setattr(assistant, "get_embedding_service", _fail_if_called)
    monkeypatch.setattr(assistant, "LocalLLMService", _fail_if_called)

    response = await client.post(
        "/assistant/ask",
        json={"question": "СКОЛЬКО ДОКУМЕНТОВ НАХОДИТСЯ В БАЗЕ?"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == (
        "В системе загружено 0 публикаций. "
        "Информация получена из внутренней базы системы."
    )
    assert response.json()["sources"] == []
    assert response.json()["answer_origin"] == "internal"
    assert response.json()["answer_blocks"][0]["source_ids"] == []


@pytest.mark.parametrize(
    "question",
    [
        "Сколько статей посвящено Байкалу?",
        "Сколько статей о систематике растений?",
        "Сколько статей о базальтах?",
    ],
)
def test_topic_specific_count_question_remains_a_rag_question(question):
    assert not is_publication_count_question(question)
