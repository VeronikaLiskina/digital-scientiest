import pytest


@pytest.mark.asyncio
async def test_publication_import_batch_creates_review_items_without_catalog_writes(
    client,
    monkeypatch,
):
    from app.api import publication_imports
    from app.services.pdf_import import ExtractedPublicationMetadata

    existing_author = await client.post(
        "/api/authors",
        json={"full_name": "Иванов И.И.", "organization": ""},
    )
    existing_keyword = await client.post("/api/keywords", json={"name": "геохимия"})
    existing_topic = await client.post(
        "/api/topics",
        json={"name": "Геохимия", "description": ""},
    )

    def fake_extract(_file_path, original_name=None):
        return ExtractedPublicationMetadata(
            title=f"Title from {original_name}",
            year=2024,
            language="ru",
            publication_type="article",
            doi=None,
            authors=["Иванов И.И.", "Петров П.П."],
            keywords=["геохимия", "цирконы"],
            topics=["Геохимия"],
            title_source="pdf",
            title_confidence="high",
            title_warning=None,
        )

    monkeypatch.setattr(publication_imports, "extract_publication_metadata_from_pdf", fake_extract)

    response = await client.post(
        "/api/publication-imports",
        files=[
            ("files", ("first.pdf", b"%PDF-1.4 first", "application/pdf")),
            ("files", ("second.pdf", b"%PDF-1.4 second", "application/pdf")),
        ],
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "needs_review"
    assert data["total_files"] == 2
    assert data["needs_review_count"] == 2
    assert len(data["items"]) == 2

    first_item = data["items"][0]
    assert first_item["status"] == "needs_review"
    assert first_item["extracted_metadata"]["matched_author_ids"] == [existing_author.json()["id"]]
    assert first_item["extracted_metadata"]["matched_keyword_ids"] == [existing_keyword.json()["id"]]
    assert first_item["extracted_metadata"]["matched_topic_ids"] == [existing_topic.json()["id"]]
    assert first_item["extracted_metadata"]["new_authors"] == ["Петров П.П."]
    assert first_item["extracted_metadata"]["new_keywords"] == ["цирконы"]

    assert len((await client.get("/api/authors")).json()) == 1
    assert len((await client.get("/api/keywords")).json()) == 1
    assert len((await client.get("/api/topics")).json()) == 1


@pytest.mark.asyncio
async def test_publication_import_duplicate_and_error_items_are_isolated(
    client,
    tmp_path,
    monkeypatch,
):
    from app.api import publication_imports
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))

    await client.post(
        "/api/source-files/upload",
        files={"file": ("same.pdf", b"%PDF-1.4 same", "application/pdf")},
    )

    response = await client.post(
        "/api/publication-imports",
        files=[
            ("files", ("duplicate.pdf", b"%PDF-1.4 same", "application/pdf")),
            ("files", ("bad.txt", b"not pdf", "text/plain")),
        ],
    )

    assert response.status_code == 201
    items = response.json()["items"]

    assert [item["status"] for item in items] == ["duplicate", "error"]
    assert "уже загружен" in items[0]["error_message"]
    assert "Only PDF files" in items[1]["error_message"]


@pytest.mark.asyncio
async def test_create_publication_marks_import_item_saved(client, monkeypatch):
    from app.api import publication_imports
    from app.services import pdf_processing_queue
    from app.services.pdf_import import ExtractedPublicationMetadata

    def fake_extract(_file_path, original_name=None):
        return ExtractedPublicationMetadata(
            title="Проверяемая публикация",
            year=2025,
            language="ru",
            publication_type="article",
            doi=None,
            authors=["Иванов И.И."],
            keywords=["геохимия"],
            topics=["Геохимия"],
            title_source="pdf",
            title_confidence="high",
            title_warning=None,
        )

    monkeypatch.setattr(publication_imports, "extract_publication_metadata_from_pdf", fake_extract)
    queued_source_file_ids: list[int] = []
    monkeypatch.setattr(
        pdf_processing_queue,
        "_start_processing_task",
        queued_source_file_ids.append,
    )

    batch_response = await client.post(
        "/api/publication-imports",
        files={"files": ("article.pdf", b"%PDF-1.4 article", "application/pdf")},
    )
    item = batch_response.json()["items"][0]

    create_response = await client.post(
        "/api/publications",
        json={
            "import_item_id": item["id"],
            "source_file_id": item["source_file_id"],
            "title": item["extracted_metadata"]["title"],
            "year": item["extracted_metadata"]["year"],
            "language": item["extracted_metadata"]["language"],
            "publication_type": "article",
            "status": "draft",
            "author_ids": [],
            "topic_ids": [],
            "keyword_ids": [],
            "author_names": ["Иванов И.И."],
            "topic_names": ["Геохимия"],
            "keyword_names": ["геохимия"],
        },
    )

    assert create_response.status_code == 201

    batch_after = await client.get(f"/api/publication-imports/{batch_response.json()['id']}")
    saved_item = batch_after.json()["items"][0]
    assert saved_item["status"] == "saved"
    assert saved_item["processing_status"] == "queued"
    assert saved_item["publication_id"] == create_response.json()["id"]
    assert batch_after.json()["saved_count"] == 1
    assert batch_after.json()["needs_review_count"] == 0
    assert queued_source_file_ids == [item["source_file_id"]]
