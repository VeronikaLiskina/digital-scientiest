import pytest

from app.core.config import settings


async def create_author(client, full_name="Иванов Иван Иванович"):
    response = await client.post(
        "/api/authors",
        json={
            "full_name": full_name,
            "organization": "ИРНИТУ",
        },
    )

    assert response.status_code == 201
    return response.json()


async def create_topic(client, name="Искусственный интеллект"):
    response = await client.post(
        "/api/topics",
        json={
            "name": name,
            "description": "Тестовая тема",
        },
    )

    assert response.status_code == 201
    return response.json()


async def create_keyword(client, name="RAG"):
    response = await client.post(
        "/api/keywords",
        json={
            "name": name,
        },
    )

    assert response.status_code == 201
    return response.json()


async def create_source_file(client):
    response = await client.post(
        "/api/source-files",
        json={
            "file_name": "article.pdf",
            "file_path": "uploads/article.pdf",
            "file_type": "application/pdf",
            "processing_status": "new",
        },
    )

    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_create_publication_with_relations(client):
    author = await create_author(client)
    topic = await create_topic(client)
    keyword = await create_keyword(client)
    source_file = await create_source_file(client)

    response = await client.post(
        "/api/publications",
        json={
            "title": "Разработка научного блока системы Цифровой учёный",
            "year": 2026,
            "language": "ru",
            "publication_type": "article",
            "doi": "10.1234/test",
            "status": "draft",
            "source_file_id": source_file["id"],
            "author_ids": [author["id"]],
            "topic_ids": [topic["id"]],
            "keyword_ids": [keyword["id"]],
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["title"] == "Разработка научного блока системы Цифровой учёный"
    assert data["year"] == 2026
    assert data["language"] == "ru"
    assert data["publication_type"] == "article"
    assert data["doi"] == "10.1234/test"
    assert data["status"] == "draft"
    assert data["source_file_id"] == source_file["id"]

    assert len(data["authors"]) == 1
    assert data["authors"][0]["id"] == author["id"]

    assert len(data["topics"]) == 1
    assert data["topics"][0]["id"] == topic["id"]

    assert len(data["keywords"]) == 1
    assert data["keywords"][0]["id"] == keyword["id"]


@pytest.mark.asyncio
async def test_get_publication_by_id(client):
    author = await create_author(client)

    create_response = await client.post(
        "/api/publications",
        json={
            "title": "Тестовая публикация",
            "year": 2025,
            "status": "draft",
            "author_ids": [author["id"]],
            "topic_ids": [],
            "keyword_ids": [],
        },
    )

    publication_id = create_response.json()["id"]

    response = await client.get(f"/api/publications/{publication_id}")

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == publication_id
    assert data["title"] == "Тестовая публикация"
    assert len(data["authors"]) == 1
    assert data["authors"][0]["id"] == author["id"]


@pytest.mark.asyncio
async def test_get_publications_with_filters(client):
    author = await create_author(client, full_name="Автор Фильтра")
    topic = await create_topic(client, name="Базы данных")
    keyword = await create_keyword(client, name="PostgreSQL")

    await client.post(
        "/api/publications",
        json={
            "title": "Публикация про PostgreSQL",
            "year": 2026,
            "language": "ru",
            "status": "draft",
            "author_ids": [author["id"]],
            "topic_ids": [topic["id"]],
            "keyword_ids": [keyword["id"]],
        },
    )

    await client.post(
        "/api/publications",
        json={
            "title": "Другая публикация",
            "year": 2024,
            "language": "en",
            "status": "draft",
            "author_ids": [],
            "topic_ids": [],
            "keyword_ids": [],
        },
    )

    response = await client.get(
        "/api/publications",
        params={
            "title": "PostgreSQL",
            "year": 2026,
            "author_id": author["id"],
            "topic_id": topic["id"],
            "keyword_id": keyword["id"],
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["title"] == "Публикация про PostgreSQL"
    assert data[0]["year"] == 2026


@pytest.mark.asyncio
async def test_update_publication(client):
    first_author = await create_author(client, full_name="Первый автор")
    second_author = await create_author(client, full_name="Второй автор")

    create_response = await client.post(
        "/api/publications",
        json={
            "title": "Старое название",
            "year": 2024,
            "status": "draft",
            "author_ids": [first_author["id"]],
            "topic_ids": [],
            "keyword_ids": [],
        },
    )

    publication_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/publications/{publication_id}",
        json={
            "title": "Новое название",
            "year": 2026,
            "status": "published",
            "author_ids": [second_author["id"]],
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == publication_id
    assert data["title"] == "Новое название"
    assert data["year"] == 2026
    assert data["status"] == "published"

    assert len(data["authors"]) == 1
    assert data["authors"][0]["id"] == second_author["id"]


@pytest.mark.asyncio
async def test_create_publication_with_unknown_author_returns_400(client):
    response = await client.post(
        "/api/publications",
        json={
            "title": "Публикация с несуществующим автором",
            "year": 2026,
            "status": "draft",
            "author_ids": [999],
            "topic_ids": [],
            "keyword_ids": [],
        },
    )

    assert response.status_code == 400
    assert "ids do not exist" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_publication(client):
    create_response = await client.post(
        "/api/publications",
        json={
            "title": "Публикация для удаления",
            "year": 2026,
            "status": "draft",
            "author_ids": [],
            "topic_ids": [],
            "keyword_ids": [],
        },
    )

    publication_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/publications/{publication_id}")

    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/publications/{publication_id}")

    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_publication_cleans_exclusive_resources_and_keeps_shared(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    pdf_path = tmp_path / "publication-cleanup.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 cleanup test")

    source_response = await client.post(
        "/api/source-files",
        json={
            "file_name": pdf_path.name,
            "file_path": str(pdf_path),
            "file_type": "application/pdf",
            "processing_status": "processed",
        },
    )
    assert source_response.status_code == 201
    source_file_id = source_response.json()["id"]

    exclusive_author = await create_author(client, "Exclusive Cleanup Author")
    shared_author = await create_author(client, "Shared Cleanup Author")
    exclusive_topic = await create_topic(client, "Exclusive Cleanup Topic")
    shared_topic = await create_topic(client, "Shared Cleanup Topic")
    exclusive_keyword = await create_keyword(client, "exclusive-cleanup-keyword")
    shared_keyword = await create_keyword(client, "shared-cleanup-keyword")

    shared_publication_response = await client.post(
        "/api/publications",
        json={
            "title": "Publication keeping shared catalog entries",
            "status": "draft",
            "author_ids": [shared_author["id"]],
            "topic_ids": [shared_topic["id"]],
            "keyword_ids": [shared_keyword["id"]],
        },
    )
    assert shared_publication_response.status_code == 201

    deleted_publication_response = await client.post(
        "/api/publications",
        json={
            "title": "Publication with resources to clean",
            "status": "draft",
            "source_file_id": source_file_id,
            "author_ids": [exclusive_author["id"], shared_author["id"]],
            "topic_ids": [exclusive_topic["id"], shared_topic["id"]],
            "keyword_ids": [exclusive_keyword["id"], shared_keyword["id"]],
        },
    )
    assert deleted_publication_response.status_code == 201
    publication_id = deleted_publication_response.json()["id"]

    chunk_response = await client.post(
        "/api/document-chunks",
        json={
            "publication_id": publication_id,
            "chunk_text": "Chunk removed with its publication",
            "page_number": 1,
            "chunk_index": 0,
        },
    )
    assert chunk_response.status_code == 201
    chunk_id = chunk_response.json()["id"]

    log_response = await client.post(
        "/api/processing-logs",
        json={
            "source_file_id": source_file_id,
            "publication_id": publication_id,
            "step_name": "cleanup-test",
            "status": "success",
        },
    )
    assert log_response.status_code == 201
    log_id = log_response.json()["id"]

    delete_response = await client.delete(f"/api/publications/{publication_id}")

    assert delete_response.status_code == 204
    assert not pdf_path.exists()
    assert (await client.get(f"/api/source-files/{source_file_id}")).status_code == 404
    assert (await client.get(f"/api/document-chunks/{chunk_id}")).status_code == 404
    assert (await client.get(f"/api/processing-logs/{log_id}")).status_code == 404

    assert (await client.get(f"/api/authors/{exclusive_author['id']}")).status_code == 404
    assert (await client.get(f"/api/topics/{exclusive_topic['id']}")).status_code == 404
    assert (await client.get(f"/api/keywords/{exclusive_keyword['id']}")).status_code == 404

    assert (await client.get(f"/api/authors/{shared_author['id']}")).status_code == 200
    assert (await client.get(f"/api/topics/{shared_topic['id']}")).status_code == 200
    assert (await client.get(f"/api/keywords/{shared_keyword['id']}")).status_code == 200
