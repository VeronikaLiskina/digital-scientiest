import pytest

from app.api import assistant
from app.services.publication_query_service import is_publication_catalog_question


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("RAG services must not be used for publication catalog questions")


async def _create_catalog_publications(client) -> None:
    author_response = await client.post(
        "/api/authors",
        json={"full_name": "Иванов И. И.", "organization": "ИРНИТУ"},
    )
    assert author_response.status_code == 201
    author_id = author_response.json()["id"]

    first_response = await client.post(
        "/api/publications",
        json={
            "title": "Первая статья",
            "year": 2024,
            "publication_type": "article",
            "author_ids": [author_id],
            "topic_ids": [],
            "keyword_ids": [],
        },
    )
    second_response = await client.post(
        "/api/publications",
        json={
            "title": "Документ без метаданных",
            "author_ids": [],
            "topic_ids": [],
            "keyword_ids": [],
        },
    )
    assert first_response.status_code == 201
    assert second_response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Какие статьи есть?",
        "Какие статьи есть в системе?",
        "Покажи все публикации",
        "Перечисли загруженные статьи",
        "Какие документы находятся в базе?",
    ],
)
async def test_publication_catalog_questions_return_database_catalog_without_rag(
    client,
    monkeypatch,
    question,
):
    await _create_catalog_publications(client)
    monkeypatch.setattr(assistant, "get_embedding_service", _fail_if_called)
    monkeypatch.setattr(assistant, "LocalLLMService", _fail_if_called)
    monkeypatch.setattr(assistant, "SemanticSearchRepository", _fail_if_called)

    response = await client.post(
        "/assistant/ask",
        json={"question": question, "limit": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == (
        "Во внутренней базе системы найдено 2 публикации. "
        "Ниже приведён полный каталог."
    )
    assert data["sources"] == []
    assert data["answer_origin"] == "catalog"
    assert data["answer_blocks"] == [{"text": data["answer"], "source_ids": []}]
    assert data["catalog"] == {
        "total": 2,
        "returned_count": 2,
        "truncated": False,
        "items": [
            {
                "publication_id": 1,
                "title": "Первая статья",
                "year": 2024,
                "authors": ["Иванов И.И."],
                "publication_type": "article",
                "publication_url": "/publications/1",
                "description": None,
            },
            {
                "publication_id": 2,
                "title": "Документ без метаданных",
                "year": None,
                "authors": [],
                "publication_type": None,
                "publication_url": "/publications/2",
                "description": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_publication_catalog_question_handles_empty_database(client, monkeypatch):
    monkeypatch.setattr(assistant, "get_embedding_service", _fail_if_called)
    monkeypatch.setattr(assistant, "LocalLLMService", _fail_if_called)

    response = await client.post(
        "/assistant/ask",
        json={"question": "Покажите все документы"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Во внутренней базе системы пока нет публикаций."
    assert data["answer_origin"] == "catalog"
    assert data["answer_blocks"] == [{"text": data["answer"], "source_ids": []}]
    assert data["sources"] == []
    assert data["catalog"] == {
        "total": 0,
        "returned_count": 0,
        "truncated": False,
        "items": [],
    }


@pytest.mark.asyncio
async def test_publication_catalog_is_saved_in_chat_history(client, monkeypatch):
    await _create_catalog_publications(client)
    monkeypatch.setattr(assistant, "get_embedding_service", _fail_if_called)

    created = await client.post("/assistant/chats", json={})
    chat_id = created.json()["id"]
    reply = await client.post(
        f"/assistant/chats/{chat_id}/messages",
        json={"content": "Покажи все публикации", "limit": 1},
    )

    assert reply.status_code == 200
    assert reply.json()["assistant_message"]["catalog"]["returned_count"] == 2
    assert reply.json()["assistant_message"]["answer_origin"] == "catalog"
    assert reply.json()["assistant_message"]["answer_blocks"] == [
        {
            "text": reply.json()["assistant_message"]["content"],
            "source_ids": [],
        }
    ]

    reopened = await client.get(f"/assistant/chats/{chat_id}")
    assistant_message = reopened.json()["messages"][1]
    assert assistant_message["catalog"] == reply.json()["assistant_message"]["catalog"]
    assert assistant_message["answer_origin"] == "catalog"


@pytest.mark.parametrize(
    "question",
    [
        "Какие статьи посвящены Байкалу?",
        "Покажи публикации о магматизме",
    ],
)
def test_topic_specific_publication_request_remains_a_rag_question(question):
    assert not is_publication_catalog_question(question)
