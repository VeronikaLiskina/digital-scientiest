import pytest

from app.models.topic import Topic
from app.services.topic_suggester import suggest_topic_names
from tests.conftest import TestingSessionLocal


class FakeEmbeddingService:
    def embed_texts(self, texts):
        return [
            [1.0, 0.0],
            [0.9, 0.1],
            [0.1, 0.9],
        ]

    def embed_text(self, text):
        if "нейросет" in text.lower() or "модель" in text.lower():
            return [0.95, 0.05]
        return [0.1, 0.9]


@pytest.mark.asyncio
async def test_suggest_topic_names_uses_embedding_similarity_when_tokens_do_not_match():
    async with TestingSessionLocal() as db:
        db.add(Topic(name="Глубокое обучение", normalized_name="глубокое обучение"))
        await db.commit()

        result = await suggest_topic_names(
            db,
            title="Нейросетевые модели для анализа данных",
            keywords=[],
            embedding_service=FakeEmbeddingService(),
        )

    assert result == ["Глубокое обучение"]


@pytest.mark.asyncio
async def test_create_topic(client):
    response = await client.post(
        "/api/topics",
        json={
            "name": "Искусственный интеллект",
            "description": "Публикации по ИИ",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["name"] == "Искусственный интеллект"
    assert data["description"] == "Публикации по ИИ"


@pytest.mark.asyncio
async def test_get_topics_with_search(client):
    await client.post(
        "/api/topics",
        json={
            "name": "Машинное обучение",
            "description": "ML",
        },
    )
    await client.post(
        "/api/topics",
        json={
            "name": "Базы данных",
            "description": "DB",
        },
    )

    response = await client.get("/api/topics", params={"search": "Базы"})

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["name"] == "Базы данных"


@pytest.mark.asyncio
async def test_update_topic(client):
    create_response = await client.post(
        "/api/topics",
        json={
            "name": "Старая тема",
            "description": "Старое описание",
        },
    )

    topic_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/topics/{topic_id}",
        json={
            "name": "Новая тема",
            "description": "Новое описание",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["name"] == "Новая тема"
    assert data["description"] == "Новое описание"


@pytest.mark.asyncio
async def test_delete_topic(client):
    create_response = await client.post(
        "/api/topics",
        json={
            "name": "Тема для удаления",
            "description": "Описание",
        },
    )

    topic_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/topics/{topic_id}")

    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/topics/{topic_id}")

    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_create_keyword(client):
    response = await client.post(
        "/api/keywords",
        json={
            "name": "RAG",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["name"] == "RAG"


@pytest.mark.asyncio
async def test_get_keywords_with_search(client):
    await client.post("/api/keywords", json={"name": "PostgreSQL"})
    await client.post("/api/keywords", json={"name": "FastAPI"})

    response = await client.get("/api/keywords", params={"search": "Fast"})

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["name"] == "FastAPI"


@pytest.mark.asyncio
async def test_update_keyword(client):
    create_response = await client.post(
        "/api/keywords",
        json={
            "name": "old-keyword",
        },
    )

    keyword_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/keywords/{keyword_id}",
        json={
            "name": "new-keyword",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["name"] == "new-keyword"


@pytest.mark.asyncio
async def test_delete_keyword(client):
    create_response = await client.post(
        "/api/keywords",
        json={
            "name": "keyword-for-delete",
        },
    )

    keyword_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/keywords/{keyword_id}")

    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/keywords/{keyword_id}")

    assert get_response.status_code == 404