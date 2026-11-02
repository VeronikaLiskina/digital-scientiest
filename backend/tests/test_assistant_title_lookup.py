import pytest

from app.api import assistant
from app.services import assistant_conversation_service


def no_model(*args, **kwargs):
    pytest.fail("Known publication titles must be resolved from the database without any model")


@pytest.fixture(autouse=True)
def prevent_models(monkeypatch):
    monkeypatch.setattr(assistant, "get_embedding_service", no_model)
    monkeypatch.setattr(assistant, "get_reranker_service", no_model)
    monkeypatch.setattr(assistant, "LocalLLMService", no_model)
    monkeypatch.setattr(assistant_conversation_service, "LocalLLMService", no_model)


async def seed(client):
    ids = []
    for title in [
        "МЕЛОВАЯ СИСТЕМА РОССИИ И БЛИЖНЕГО ЗАРУБЕЖЬЯ: ПРОБЛЕМЫ СТРАТИГРАФИИ И ПАЛЕОГЕОГРАФИИ",
        "ЮРСКАЯ СИСТЕМА РОССИИ: СТРАТИГРАФИЯ",
        "Basalt Rift Evolution: New Data from Siberia",
        "Мелкая система местного управления",
    ]:
        response = await client.post("/api/publications", json={"title": title, "year": 2007, "author_ids": [], "topic_ids": [], "keyword_ids": []})
        assert response.status_code == 201
        ids.append(response.json()["id"])
    await client.post("/api/document-chunks", json={"publication_id": ids[0], "chunk_index": 0,
        "chunk_text": "[section: Abstract]\nПубликация посвящена проблемам стратиграфии меловой системы и палеогеографии России и ближнего зарубежья."})
    return ids


@pytest.mark.parametrize("mode", ["auto", "publications", "general"])
async def test_bare_partial_title_wins_over_general_conversation_in_every_mode(client, mode):
    ids = await seed(client)
    response = await client.post("/assistant/ask", json={"question": "МЕЛОВАЯ СИСТЕМА РОССИИ", "mode": mode})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["answer_origin"] == "catalog"
    assert [item["publication_id"] for item in data["catalog"]["items"]] == [ids[0]]
    assert "стратиграфии" in data["catalog"]["items"][0]["description"]
    assert data["sources"] == []


@pytest.mark.parametrize(("question", "position"), [
    ("меловая система россии", 0),
    ('Покажи статью «Меловая система России»', 0),
    ('Найди сборник «Меловая система России и ближнего зарубежья»', 0),
    ('Можешь найти мне сборник «Меловая система России»?', 0),
    ('Найди «Меловая система России»', 0),
    ('Покажи документ под названием «Меловая система России»', 0),
    ('Find the book "Basalt Rift Evolution"', 2),
    ('О чём сборник «Меловая система России»?', 0),
    ("Найди статью Меловая система России", 0),
    ("Расскажи о Меловая система России", 0),
    ("ЮРСКАЯ СИСТЕМА РОССИИ", 1),
    ("Basalt Rift Evolution", 2),
    ("Проблемы стратиграфии и палеогеографии", 0),
])
async def test_titles_are_generic_and_ignore_case_and_punctuation(client, question, position):
    ids = await seed(client)
    response = await client.post("/assistant/ask", json={"question": question})
    assert response.status_code == 200, response.text
    assert [item["publication_id"] for item in response.json()["catalog"]["items"]] == [ids[position]]


async def test_unknown_explicit_title_is_not_silently_replaced(client):
    await seed(client)
    response = await client.post("/assistant/ask", json={"question": 'Найди статью «МЕЛКАЯ СИСТЕМА РОССИИ»'})
    assert response.status_code == 200, response.text
    assert response.json()["answer_origin"] == "catalog"
    assert response.json()["catalog"]["total"] == 0


async def test_title_after_general_chat_and_description_followup_stay_in_catalog(client, monkeypatch):
    ids = await seed(client)
    chat = (await client.post("/assistant/chats", json={})).json()["id"]

    class GreetingModel:
        async def generate_general_knowledge_answer(self, *args, **kwargs):
            return "Привет!"

    monkeypatch.setattr(assistant_conversation_service, "LocalLLMService", GreetingModel)
    greeting = await client.post(f"/assistant/chats/{chat}/messages", json={"content": "Привет"})
    assert greeting.status_code == 200, greeting.text
    assert greeting.json()["assistant_message"]["answer_origin"] == "external"
    monkeypatch.setattr(assistant_conversation_service, "LocalLLMService", no_model)

    for question in ["МЕЛОВАЯ СИСТЕМА РОССИИ", "О чём она?"]:
        response = await client.post(f"/assistant/chats/{chat}/messages", json={"content": question})
        assert response.status_code == 200, response.text
        message = response.json()["assistant_message"]
        assert message["answer_origin"] == "catalog"
        assert [item["publication_id"] for item in message["catalog"]["items"]] == [ids[0]]


@pytest.mark.parametrize("mode", ["auto", "publications", "general"])
async def test_collection_lookup_from_screenshot_does_not_use_models(client, mode):
    ids = await seed(client)
    response = await client.post("/assistant/ask", json={
        "question": 'Найди сборник «Меловая система России и ближнего зарубежья»', "mode": mode,
    })
    assert response.status_code == 200, response.text
    assert response.json()["answer_origin"] == "catalog"
    assert [item["publication_id"] for item in response.json()["catalog"]["items"]] == [ids[0]]


@pytest.mark.parametrize("mode", ["auto", "publications", "general"])
async def test_missing_quoted_collection_never_turns_into_general_knowledge(client, mode):
    await seed(client)
    response = await client.post("/assistant/ask", json={
        "question": 'Найди сборник «Неподтверждённое название сборника»', "mode": mode,
    })
    assert response.status_code == 200, response.text
    assert response.json()["answer_origin"] == "catalog"
    assert response.json()["catalog"]["total"] == 0


async def test_content_question_with_missing_document_does_not_search_other_publications(client):
    await seed(client)
    response = await client.post("/assistant/ask", json={
        "question": 'Какие методы использованы в книге «Неподтверждённое название»?',
    })
    assert response.status_code == 200, response.text
    assert response.json()["answer_origin"] == "internal"
    assert response.json()["sources"] == []


async def test_content_retrieval_keeps_actual_document_ids_and_resets_on_new_topic(client, monkeypatch):
    ids = await seed(client)
    scopes = []

    class Retrieval:
        def __init__(self, **kwargs):
            scopes.append(kwargs["repository"].publication_ids)

        async def retrieve(self, **kwargs):
            return []

    class RewriteOnly:
        async def rewrite_followup_query(self, question, context):
            return question

    monkeypatch.setattr(assistant, "get_embedding_service", lambda: object())
    monkeypatch.setattr(assistant, "LocalLLMService", RewriteOnly)
    monkeypatch.setattr(assistant, "AssistantRetrievalService", Retrieval)
    chat = (await client.post("/assistant/chats", json={})).json()["id"]
    for question in [
        'Найди сборник «Меловая система России»',
        "Какие методы там использованы?",
        "Что известно об Уджинском палеорифте?",
    ]:
        response = await client.post(f"/assistant/chats/{chat}/messages", json={"content": question, "mode": "publications"})
        assert response.status_code == 200, response.text
    assert scopes == [(ids[0],), None]

    response = await client.post("/assistant/ask", json={
        "question": 'Какие методы описаны в сборнике «Меловая система России»?',
    })
    assert response.status_code == 200, response.text
    assert scopes[-1] == (ids[0],)


async def test_bare_title_count_and_singular_followup_use_persisted_selection(client):
    ids = await seed(client)
    chat = (await client.post("/assistant/chats", json={})).json()["id"]
    for question in ["МЕЛОВАЯ СИСТЕМА РОССИИ", "О чём он?", "Сколько их?"]:
        response = await client.post(f"/assistant/chats/{chat}/messages", json={"content": question})
        assert response.status_code == 200, response.text
        message = response.json()["assistant_message"]
        if question != "Сколько их?":
            assert [item["publication_id"] for item in message["catalog"]["items"]] == [ids[0]]
    assert message["answer_origin"] == "internal"
    assert "1" in message["content"]
