import pytest

from app.api import assistant
from app.services.publication_query_service import (
    DESCRIPTION_UNAVAILABLE,
    build_representative_description,
    is_publication_catalog_with_descriptions_question,
)


FIRST_DESCRIPTION = (
    "Исследование рассматривает строение земной коры региона и сопоставляет "
    "результаты полевых наблюдений с геофизическими измерениями."
)
SECOND_DESCRIPTION = (
    "Авторы анализируют состав магматических пород и последовательность этапов "
    "формирования исследованного геологического комплекса."
)


def _fail_if_called(*_args, **_kwargs):
    raise AssertionError("RAG and LLM services must not be used for described catalogs")


async def _create_publications_with_chunks(client) -> None:
    publication_ids: list[int] = []
    for title in (
        "Строение земной коры",
        "Магматические породы",
        "Необработанная публикация",
    ):
        response = await client.post(
            "/api/publications",
            json={
                "title": title,
                "author_ids": [],
                "topic_ids": [],
                "keyword_ids": [],
            },
        )
        assert response.status_code == 201
        publication_ids.append(response.json()["id"])

    chunks = [
        (
            publication_ids[0],
            0,
            "[section: Metadata]\n[page: 1]\n"
            "Авторы, организации, адреса электронной почты, лицензия и прочие "
            "служебные сведения о публикации, которые не описывают исследование.",
        ),
        (
            publication_ids[0],
            1,
            f"[section: Abstract]\n[page: 1]\n{FIRST_DESCRIPTION}\n",
        ),
        (
            publication_ids[0],
            2,
            "Этот более поздний фрагмент не должен заменять первый содержательный фрагмент публикации.",
        ),
        (publication_ids[1], 0, SECOND_DESCRIPTION),
    ]
    for publication_id, chunk_index, chunk_text in chunks:
        response = await client.post(
            "/api/document-chunks",
            json={
                "publication_id": publication_id,
                "chunk_text": chunk_text,
                "page_number": 1,
                "chunk_index": chunk_index,
                "embedding": None,
            },
        )
        assert response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "О чём статьи?",
        "Сколько публикаций в системе и о чём они?",
        "Какие статьи есть в системе и о чём они?",
        "Перечисли все публикации с кратким описанием",
        "Что загружено в систему? Кратко расскажи о каждой статье",
        "Какие материалы есть в базе и чему они посвящены?",
    ],
)
async def test_described_catalog_uses_each_publications_own_first_meaningful_chunk(
    client,
    monkeypatch,
    question,
):
    await _create_publications_with_chunks(client)
    monkeypatch.setattr(assistant, "get_embedding_service", _fail_if_called)
    monkeypatch.setattr(assistant, "LocalLLMService", _fail_if_called)
    monkeypatch.setattr(assistant, "SemanticSearchRepository", _fail_if_called)

    response = await client.post(
        "/assistant/ask",
        json={"question": question, "limit": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["answer_origin"] == "catalog"
    assert data["answer_blocks"] == [{"text": data["answer"], "source_ids": []}]
    assert data["sources"] == []
    assert data["catalog"]["total"] == 3
    assert data["catalog"]["returned_count"] == 3
    assert data["catalog"]["truncated"] is False
    assert "внутренней базе системы" in data["answer"]
    assert "только по обработанным фрагментам каждой публикации" in data["answer"]

    items = data["catalog"]["items"]
    assert items[0]["description"] == FIRST_DESCRIPTION
    assert items[1]["description"] == SECOND_DESCRIPTION
    assert items[2]["description"] == DESCRIPTION_UNAVAILABLE
    assert SECOND_DESCRIPTION not in items[0]["description"]
    assert FIRST_DESCRIPTION not in items[1]["description"]
    assert "более поздний фрагмент" not in items[0]["description"]


@pytest.mark.parametrize(
    "question",
    [
        "О чём статьи?",
        "Сколько публикаций в системе и о чём они?",
        "Какие статьи есть в системе и о чём они?",
        "Перечисли все публикации с кратким описанием",
        "Что загружено в систему? Кратко расскажи о каждой статье",
        "Какие материалы есть в базе и чему они посвящены?",
    ],
)
def test_described_catalog_question_detection(question):
    assert is_publication_catalog_with_descriptions_question(question)


def test_short_description_followup_requires_publication_context():
    assert not is_publication_catalog_with_descriptions_question("О чём они?")
    assert is_publication_catalog_with_descriptions_question(
        "О чём они?",
        "Пользователь: Сколько публикаций в системе?\n"
        "Ассистент: В системе загружено 3 публикации.",
    )


@pytest.mark.asyncio
async def test_chat_description_followup_uses_previous_publication_question(
    client,
    monkeypatch,
):
    await _create_publications_with_chunks(client)
    monkeypatch.setattr(assistant, "get_embedding_service", _fail_if_called)
    monkeypatch.setattr(assistant, "LocalLLMService", _fail_if_called)
    monkeypatch.setattr(assistant, "SemanticSearchRepository", _fail_if_called)

    chat = await client.post("/assistant/chats", json={})
    chat_id = chat.json()["id"]

    count_reply = await client.post(
        f"/assistant/chats/{chat_id}/messages",
        json={"content": "Сколько публикаций в системе?"},
    )
    followup_reply = await client.post(
        f"/assistant/chats/{chat_id}/messages",
        json={"content": "О чём они?"},
    )

    assert count_reply.status_code == 200
    assert followup_reply.status_code == 200
    answer = followup_reply.json()["assistant_message"]
    assert answer["answer_origin"] == "catalog"
    assert answer["sources"] == []
    assert answer["catalog"]["total"] == 3
    assert answer["catalog"]["items"][0]["description"] == FIRST_DESCRIPTION
    assert answer["catalog"]["items"][1]["description"] == SECOND_DESCRIPTION


def test_description_is_not_inferred_from_a_title_only_chunk():
    assert build_representative_description("Геология Байкальского региона") is None


def test_representative_description_is_limited_at_a_word_boundary():
    description = build_representative_description("содержательный " * 60)

    assert description is not None
    assert len(description) <= 501
    assert description.endswith("…")
    assert not description.endswith(" …")
