import pytest


TEST_EMBEDDING = [0.1] * 768


async def create_publication(client):
    response = await client.post(
        "/api/publications",
        json={
            "title": "Публикация для чанков",
            "year": 2026,
            "language": "ru",
            "publication_type": "article",
            "status": "draft",
            "author_ids": [],
            "topic_ids": [],
            "keyword_ids": [],
        },
    )

    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_create_document_chunk(client):
    publication = await create_publication(client)

    response = await client.post(
        "/api/document-chunks",
        json={
            "publication_id": publication["id"],
            "chunk_text": "Это первый фрагмент текста публикации.",
            "page_number": 1,
            "chunk_index": 0,
            "embedding": TEST_EMBEDDING,
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["publication_id"] == publication["id"]
    assert data["chunk_text"] == "Это первый фрагмент текста публикации."
    assert data["page_number"] == 1
    assert data["chunk_index"] == 0
    assert data["embedding"] == TEST_EMBEDDING


@pytest.mark.asyncio
async def test_get_document_chunk_by_id(client):
    publication = await create_publication(client)

    create_response = await client.post(
        "/api/document-chunks",
        json={
            "publication_id": publication["id"],
            "chunk_text": "Текст чанка",
            "page_number": 2,
            "chunk_index": 0,
            "embedding": None,
        },
    )

    chunk_id = create_response.json()["id"]

    response = await client.get(f"/api/document-chunks/{chunk_id}")

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == chunk_id
    assert data["chunk_text"] == "Текст чанка"


@pytest.mark.asyncio
async def test_get_document_chunks_with_publication_filter(client):
    first_publication = await create_publication(client)

    second_publication_response = await client.post(
        "/api/publications",
        json={
            "title": "Другая публикация",
            "year": 2026,
            "status": "draft",
            "author_ids": [],
            "topic_ids": [],
            "keyword_ids": [],
        },
    )

    second_publication = second_publication_response.json()

    await client.post(
        "/api/document-chunks",
        json={
            "publication_id": first_publication["id"],
            "chunk_text": "Чанк первой публикации",
            "page_number": 1,
            "chunk_index": 0,
            "embedding": None,
        },
    )

    await client.post(
        "/api/document-chunks",
        json={
            "publication_id": second_publication["id"],
            "chunk_text": "Чанк второй публикации",
            "page_number": 1,
            "chunk_index": 0,
            "embedding": None,
        },
    )

    response = await client.get(
        "/api/document-chunks",
        params={"publication_id": first_publication["id"]},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["publication_id"] == first_publication["id"]
    assert data[0]["chunk_text"] == "Чанк первой публикации"


@pytest.mark.asyncio
async def test_update_document_chunk(client):
    publication = await create_publication(client)

    create_response = await client.post(
        "/api/document-chunks",
        json={
            "publication_id": publication["id"],
            "chunk_text": "Старый текст",
            "page_number": 1,
            "chunk_index": 0,
            "embedding": None,
        },
    )

    chunk_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/document-chunks/{chunk_id}",
        json={
            "chunk_text": "Новый текст",
            "page_number": 3,
            "chunk_index": 1,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == chunk_id
    assert data["chunk_text"] == "Новый текст"
    assert data["page_number"] == 3
    assert data["chunk_index"] == 1
    assert data["embedding"] is None


@pytest.mark.asyncio
async def test_create_document_chunk_with_unknown_publication_returns_400(client):
    response = await client.post(
        "/api/document-chunks",
        json={
            "publication_id": 999,
            "chunk_text": "Текст без публикации",
            "page_number": 1,
            "chunk_index": 0,
            "embedding": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Publication not found"


@pytest.mark.asyncio
async def test_delete_document_chunk(client):
    publication = await create_publication(client)

    create_response = await client.post(
        "/api/document-chunks",
        json={
            "publication_id": publication["id"],
            "chunk_text": "Чанк для удаления",
            "page_number": 1,
            "chunk_index": 0,
            "embedding": None,
        },
    )

    chunk_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/document-chunks/{chunk_id}")

    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/document-chunks/{chunk_id}")

    assert get_response.status_code == 404
