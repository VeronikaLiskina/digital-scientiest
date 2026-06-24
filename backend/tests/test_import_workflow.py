import pytest


@pytest.mark.asyncio
async def test_author_keyword_topic_are_not_duplicated_by_normalized_name(client):
    first_author = await client.post(
        "/api/authors",
        json={"full_name": "Иванов И. И.", "organization": "ИРНИТУ"},
    )
    second_author = await client.post(
        "/api/authors",
        json={"full_name": " Иванов И.И. ", "organization": "Другая организация"},
    )

    assert first_author.status_code == 201
    assert second_author.status_code == 201
    assert first_author.json()["id"] == second_author.json()["id"]

    first_keyword = await client.post("/api/keywords", json={"name": "RAG"})
    second_keyword = await client.post("/api/keywords", json={"name": " rag "})

    assert first_keyword.status_code == 201
    assert second_keyword.status_code == 201
    assert first_keyword.json()["id"] == second_keyword.json()["id"]

    first_topic = await client.post(
        "/api/topics",
        json={"name": "Искусственный интеллект", "description": "ИИ"},
    )
    second_topic = await client.post(
        "/api/topics",
        json={"name": " искусственный интеллект ", "description": "AI"},
    )

    assert first_topic.status_code == 201
    assert second_topic.status_code == 201
    assert first_topic.json()["id"] == second_topic.json()["id"]

    assert len((await client.get("/api/authors")).json()) == 1
    assert len((await client.get("/api/keywords")).json()) == 1
    assert len((await client.get("/api/topics")).json()) == 1


@pytest.mark.asyncio
async def test_duplicate_pdf_upload_returns_409(client, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))

    payload = b"%PDF-1.4\n% same pdf content"

    first_response = await client.post(
        "/api/source-files/upload",
        files={"file": ("same.pdf", payload, "application/pdf")},
    )
    second_response = await client.post(
        "/api/source-files/upload",
        files={"file": ("same.pdf", payload, "application/pdf")},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "Такой PDF уже загружался"


@pytest.mark.asyncio
async def test_extract_metadata_endpoint_does_not_save_file_and_suggests_existing_topics(client, monkeypatch):
    from app.api import source_files
    from app.services.pdf_import import ExtractedPublicationMetadata

    await client.post(
        "/api/topics",
        json={"name": "Искусственный интеллект", "description": "ИИ"},
    )

    def fake_extract(_content: bytes, original_name: str | None = None):
        return ExtractedPublicationMetadata(
            title="Искусственный интеллект в научных публикациях",
            year=2024,
            language="ru",
            publication_type="article",
            doi="10.1234/test",
            authors=["Иванов И.И."],
            keywords=["RAG", "искусственный интеллект"],
            topics=[],
            title_source="pdf",
            title_confidence="high",
            title_warning=None,
        )

    monkeypatch.setattr(source_files, "extract_publication_metadata_from_bytes", fake_extract)

    response = await client.post(
        "/api/source-files/extract-metadata",
        files={"file": ("article.pdf", b"%PDF-1.4 test", "application/pdf")},
    )

    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "metadata_extracted"
    assert data["review_status"] == "needs_review"
    assert data["extracted"]["title"] == "Искусственный интеллект в научных публикациях"
    assert data["extracted"]["title_source"] == "pdf"
    assert data["extracted"]["title_confidence"] == "high"
    assert data["extracted"]["title_warning"] is None
    assert data["extracted"]["authors"] == ["Иванов И.И."]
    assert data["extracted"]["topics"] == ["Искусственный интеллект"]

    files = (await client.get("/api/source-files")).json()
    assert files == []


@pytest.mark.asyncio
async def test_create_publication_resolves_confirmed_names_only_on_submit(client):
    response = await client.post(
        "/api/publications",
        json={
            "title": "Публикация после проверки PDF",
            "year": 2026,
            "language": "ru",
            "publication_type": "article",
            "status": "draft",
            "author_ids": [],
            "topic_ids": [],
            "keyword_ids": [],
            "author_names": ["Иванов И. И.", "Иванов И.И."],
            "topic_names": ["Искусственный интеллект"],
            "keyword_names": ["RAG", " rag "],
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert len(data["authors"]) == 1
    assert data["authors"][0]["full_name"] == "Иванов И.И."
    assert len(data["topics"]) == 1
    assert data["topics"][0]["name"] == "Искусственный интеллект"
    assert len(data["keywords"]) == 1
    assert data["keywords"][0]["name"] == "RAG"
