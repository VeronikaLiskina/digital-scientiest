import pytest

from app.api import assistant
from app.services.publication_search_service import PublicationSearch, search_publications
from tests.conftest import TestingSessionLocal


def fail_model(*args, **kwargs):
    raise AssertionError("Catalog selection must not load models or call external APIs")


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    monkeypatch.setattr(assistant, "get_embedding_service", fail_model)
    monkeypatch.setattr(assistant, "get_reranker_service", fail_model)
    monkeypatch.setattr(assistant, "LocalLLMService", fail_model)


async def seed(client):
    author = (await client.post("/api/authors", json={"full_name": "Сидоров С.С."})).json()["id"]
    keyword = (await client.post("/api/keywords", json={"name": "Магнитные свойства"})).json()["id"]
    topic = (await client.post("/api/topics", json={"name": "Палеомагнетизм"})).json()["id"]
    ids = []
    rows = [
        {"title": "Палеомагнетизм гранитоидов", "year": 2023, "language": "ru", "author_ids": [author]},
        {"title": "Исследование образцов", "keyword_ids": [keyword], "year": 2021},
        {"title": "Направления поля", "topic_ids": [topic], "year": 2022},
        {"title": "Rock magnetic properties", "year": 2024, "language": "en", "publication_type": "review"},
        {"title": "Геофизическое исследование", "year": 2019},
        {"title": "Магматизм базальтов", "year": 2023},
        {"title": "Ботаника: исследование растений", "year": 2023, "author_ids": [author]},
        {"title": "Публикация только со списком литературы", "year": 2020},
        {"title": "Труды конференции", "publication_type": "conference"},
        {"title": "Учебное издание", "publication_type": "book"},
        {"title": "Отчет экспедиции", "publication_type": "report"},
        {"title": "Доклад", "publication_type": "thesis"},
    ]
    for row in rows:
        response = await client.post("/api/publications", json={
            "publication_type": "article", "author_ids": [], "keyword_ids": [], "topic_ids": [], **row,
        })
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    for pub_id, text in [
        (ids[4], "В исследовании изучены магнитные свойства образцов пород. Измерены направление и величина остаточной намагниченности."),
        (ids[7], "[section: references] Список литературы. Палеомагнетизм гранитоидов, Иванов, 2023."),
    ]:
        response = await client.post("/api/document-chunks", json={"publication_id": pub_id, "chunk_index": 0, "chunk_text": text})
        assert response.status_code == 201, response.text
    return ids


async def ask(client, question):
    response = await client.post("/assistant/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


async def test_topic_search_uses_all_fields_and_ranks_titles_first(client):
    ids = await seed(client)
    data = await ask(client, "какие публикации есть по магнитизму")
    assert data["answer_origin"] == "catalog"
    assert data["catalog"]["total"] == 5
    found = [item["publication_id"] for item in data["catalog"]["items"]]
    assert set(found) == set(ids[:5])
    assert found.index(ids[0]) < found.index(ids[4])
    assert found.index(ids[3]) < found.index(ids[4])


@pytest.mark.parametrize(("question", "positions"), [
    ("Покажи статьи по ботанике", [6]),
    ("Найди публикации автора Сидорова", [0, 6]),
    ("Подбери статьи за 2021–2022 годы", [1, 2]),
    ("Покажи обзоры на английском языке", [3]),
    ("Покажи статьи по магнитизму автора Сидорова за 2023 год на русском", [0]),
    ("Покажи статьи по геологии и ботанике", []),
    ("Покажи статьи по ботанике или магматизму", [5, 6]),
    ("Покажи публикации по теме квантовая криптография", []),
    ("Покажи материалы конференции", [8]),
    ("Покажи книги", [9]),
    ("Покажи отчеты", [10]),
    ("Покажи публикации типа тезисы", [11]),
    ("Можешь подобрать мне статьи по магнитизму?", [0, 1, 2, 3, 4]),
    ("Find publications about paleomagnetism", [0, 2]),
    ("Покажи статьи Сидорова", [0, 6]),
])
async def test_general_filters_and_combinations(client, question, positions):
    ids = await seed(client)
    data = await ask(client, question)
    assert data["answer_origin"] == "catalog"
    assert {item["publication_id"] for item in data["catalog"]["items"]} == {ids[i] for i in positions}
    assert data["catalog"]["total"] == len(positions)


async def test_filtered_count_and_pagination(client):
    await seed(client)
    data = await ask(client, "Сколько публикаций по магнитизму?")
    assert "найдено публикаций: 5" in data["answer"]
    assert data["catalog"] is None
    async with TestingSessionLocal() as db:
        total, publications = await search_publications(db, PublicationSearch(topic="магнитизм"), max_items=2)
    assert total == 5
    assert len(publications) == 2


async def test_filtered_results_saved_and_description_followup_keeps_scope(client):
    ids = await seed(client)
    chat = (await client.post("/assistant/chats", json={})).json()["id"]
    response = await client.post(f"/assistant/chats/{chat}/messages", json={"content": "Покажи статьи по ботанике"})
    assert response.status_code == 200, response.text
    response = await client.post(f"/assistant/chats/{chat}/messages", json={"content": "А о чём они?"})
    assert response.status_code == 200, response.text
    data = response.json()["assistant_message"]
    assert [item["publication_id"] for item in data["catalog"]["items"]] == [ids[6]]
    saved = (await client.get(f"/assistant/chats/{chat}")).json()["messages"][-1]
    assert saved["catalog"] == data["catalog"]


async def test_multiple_filter_followups_and_count_use_same_selection(client):
    ids = await seed(client)
    chat = (await client.post("/assistant/chats", json={})).json()["id"]
    for question in ["Подбери статьи по магнитизму", "А только с 2022 года?", "А на русском?"]:
        response = await client.post(f"/assistant/chats/{chat}/messages", json={"content": question})
        assert response.status_code == 200, response.text
    message = response.json()["assistant_message"]
    assert [item["publication_id"] for item in message["catalog"]["items"]] == [ids[0]]
    response = await client.post(f"/assistant/chats/{chat}/messages", json={"content": "Сколько их?"})
    assert response.status_code == 200, response.text
    message = response.json()["assistant_message"]
    assert "найдено публикаций: 1" in message["content"]
    assert "магнитизму" in message["content"]
    assert message["sources"] == []


async def test_coauthors_require_every_named_person_and_respect_initials(client):
    demonterova = (await client.post("/api/authors", json={"full_name": "Демонтерова Е.И."})).json()["id"]
    sidorov = (await client.post("/api/authors", json={"full_name": "Сидоров С.С."})).json()["id"]
    joint = (await client.post("/api/publications", json={"title": "Joint study", "author_ids": [demonterova, sidorov]})).json()["id"]
    only_demonterova = (await client.post("/api/publications", json={"title": "Another study", "author_ids": [demonterova]})).json()["id"]
    await client.post("/api/publications", json={"title": "Other author", "author_ids": [sidorov]})
    data = await ask(client, "Какие публикации написаны совместно Сидоровым С.С. и Демонтеровой Е.И.?")
    assert {p["publication_id"] for p in data["catalog"]["items"]} == {joint}
    data = await ask(client, "Какие публикации написаны совместно Ивановым А.В. и Демонтеровой Е.И.?")
    assert {p["publication_id"] for p in data["catalog"]["items"]} == {joint, only_demonterova}
    data = await ask(client, "Покажи публикации автора Иванова А.Б.")
    assert data["catalog"]["total"] == 0


async def test_foreign_author_participation_uses_catalogue_identity(client):
    he = (await client.post("/api/authors", json={"full_name": "Huaiyu He"})).json()["id"]
    wanted = (await client.post("/api/publications", json={"title": "Dating study", "author_ids": [he]})).json()["id"]
    await client.post("/api/publications", json={"title": "Huaiyu He is mentioned in this title"})
    data = await ask(client, "Найди работы с участием Huaiyu He.")
    assert data["answer_origin"] == "catalog"
    assert [p["publication_id"] for p in data["catalog"]["items"]] == [wanted]


async def test_existence_query_applies_year_instead_of_retrieval(client):
    wanted = (await client.post("/api/publications", json={"title": "Tomtor geochronology", "year": 2026})).json()["id"]
    await client.post("/api/publications", json={"title": "Earlier paper", "year": 2025})
    data = await ask(client, "Есть ли в базе публикации за 2026 год?")
    assert [p["publication_id"] for p in data["catalog"]["items"]] == [wanted]
    data = await ask(client, "Есть ли в базе публикации за 2035 год?")
    assert data["catalog"]["total"] == 0


@pytest.mark.parametrize(("question", "titles", "wanted"), [
    ("Найди статью о геохимии апатитов Слюдянского месторождения.", [
        "Apatite Geochemistry of the Slyudyanka Deposit, Siberia", "Apatite Geochemistry of another deposit", "Slyudyanka Deposit: structural study"], [0]),
    ("Найди публикации по Сибирским траппам.", [
        "Siberian Traps large igneous province", "Сибирские траппы", "Basaltic magmatism in Africa"], [0, 1]),
    ("Какие исследования посвящены Восточно-Африканскому рифту?", [
        "Magma mixing in the East-African Rift", "East African rift system", "Western Siberian rift systems"], [0, 1]),
])
async def test_cross_language_catalogue_search_keeps_all_requested_concepts(client, question, titles, wanted):
    ids = [(await client.post("/api/publications", json={"title": title})).json()["id"] for title in titles]
    data = await ask(client, question)
    assert data["answer_origin"] == "catalog"
    assert {p["publication_id"] for p in data["catalog"]["items"]} == {ids[i] for i in wanted}


async def test_two_coauthors_cannot_be_satisfied_by_one_abbreviated_name(client):
    john = (await client.post("/api/authors", json={"full_name": "John Smith"})).json()["id"]
    james = (await client.post("/api/authors", json={"full_name": "James Smith"})).json()["id"]
    abbreviated = (await client.post("/api/authors", json={"full_name": "J. Smith"})).json()["id"]
    await client.post("/api/publications", json={"title": "Only one Smith", "author_ids": [abbreviated]})
    joint = (await client.post("/api/publications", json={"title": "Both Smiths", "author_ids": [john, james]})).json()["id"]
    data = await ask(client, "Find papers by John Smith and James Smith")
    assert [p["publication_id"] for p in data["catalog"]["items"]] == [joint]
