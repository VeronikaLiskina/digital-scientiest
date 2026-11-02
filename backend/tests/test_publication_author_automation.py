import pytest


async def test_publication_always_has_required_author_and_keeps_coauthors(client):
    created = await client.post("/api/publications", json={
        "title": "Scientific paper", "author_names": ["John Smith"],
    })
    assert created.status_code == 201
    names = {author["full_name"] for author in created.json()["authors"]}
    assert names == {"Иванов А.В.", "John Smith"}
    updated = await client.patch(f'/api/publications/{created.json()["id"]}', json={"author_ids": []})
    assert updated.status_code == 200
    assert [a["full_name"] for a in updated.json()["authors"]] == ["Иванов А.В."]


async def test_english_author_reuses_russian_record_and_creates_new_foreign_author(client):
    existing = await client.post("/api/authors", json={"full_name": "Веселовский Р.В."})
    assert existing.status_code == 201
    response = await client.post("/api/publications", json={
        "title": "English paper", "author_names": ["R. V. Veselovsky", "John Smith"],
    })
    assert response.status_code == 201
    authors = response.json()["authors"]
    assert any(a["id"] == existing.json()["id"] for a in authors)
    assert any(a["full_name"] == "John Smith" for a in authors)
    assert not any("Veselovsky" in a["full_name"] for a in (await client.get("/api/authors")).json())


async def test_same_surname_with_conflicting_initials_is_not_linked(client):
    first = await client.post("/api/authors", json={"full_name": "Веселовский Р.В."})
    second = await client.post("/api/authors", json={"full_name": "P. A. Veselovsky"})
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


async def test_import_uses_catalogue_names_and_saved_publication_authors(client, monkeypatch, tmp_path):
    from app.api import publication_imports
    from app.core.config import settings
    from app.services.publication_metadata_models import ExtractedPublicationMetadata
    from app.services import pdf_processing_queue

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    ivanov = (await client.post("/api/authors", json={"full_name": "Иванов А.В."})).json()
    monkeypatch.setattr(publication_imports, "extract_publication_metadata_from_pdf", lambda *_args, **_kwargs:
        ExtractedPublicationMetadata("Reliable article title", 2024, "en", "article", None,
                                     ["Alexei V. Ivanov", "John Smith"], [], [], title_source="pdf"))
    monkeypatch.setattr(pdf_processing_queue.process_pdf_task, "delay", lambda _: type("Task", (), {"id": "test"})())
    batch = await client.post("/api/publication-imports", files={"files": ("paper.pdf", b"%PDF-1.4 test authors", "application/pdf")})
    assert batch.status_code == 201
    item = batch.json()["items"][0]
    assert item["verified_authors"] == ["Иванов А.В."]
    assert item["extracted_metadata"]["new_authors"] == ["John Smith"]
    saved = await client.post("/api/publications", json={
        "title": "Reviewed title", "import_item_id": item["id"],
        "author_ids": [ivanov["id"]], "author_names": ["John Smith"],
    })
    assert saved.status_code == 201
    refreshed = await client.get(f'/api/publication-imports/{batch.json()["id"]}')
    result = refreshed.json()["items"][0]
    assert set(result["verified_authors"]) == {"Иванов А.В.", "John Smith"}
    assert result["title"] == "Reviewed title"


async def test_required_author_cannot_be_deleted_or_replaced(client):
    author = (await client.post("/api/authors", json={"full_name": "Иванов А.В."})).json()
    assert (await client.delete(f'/api/authors/{author["id"]}')).status_code == 409
    assert (await client.patch(f'/api/authors/{author["id"]}', json={"full_name": "Петров П.П."})).status_code == 409


async def test_required_author_is_not_replaced_by_an_incomplete_existing_name(client):
    await client.post("/api/authors", json={"full_name": "Иванов А."})
    response = await client.post("/api/publications", json={"title": "A paper"})
    assert response.status_code == 201
    assert any(a["full_name"] == "Иванов А.В." and a["is_required"] for a in response.json()["authors"])


async def test_backfill_is_idempotent_and_preserves_existing_coauthors(client, monkeypatch):
    from tests.conftest import TestingSessionLocal
    from app.services import publication_author_policy
    from app.models.publication import Publication
    from app.models.author import Author

    async with TestingSessionLocal() as db:
        coauthor = Author(full_name="Петров П.П.")
        publication = Publication(title="Old publication", authors=[coauthor])
        db.add(publication)
        await db.commit()
        identifier = publication.id
    monkeypatch.setattr(publication_author_policy, "async_session_maker", TestingSessionLocal)
    assert await publication_author_policy.synchronize_required_publication_authors() == 1
    assert await publication_author_policy.synchronize_required_publication_authors() == 0
    response = await client.get(f"/api/publications/{identifier}")
    assert {a["full_name"] for a in response.json()["authors"]} == {"Петров П.П.", "Иванов А.В."}


async def test_unknown_ocr_author_stays_in_review_instead_of_auto_creation(client, monkeypatch, tmp_path):
    from app.api import publication_imports
    from app.core.config import settings
    from app.services.publication_metadata_models import ExtractedPublicationMetadata
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    await client.post("/api/authors", json={"full_name": "Иванов А.В."})
    monkeypatch.setattr(publication_imports, "extract_publication_metadata_from_pdf", lambda *_args, **_kwargs:
        ExtractedPublicationMetadata("Scanned publication", 2024, "en", "article", None,
                                     ["A. V. Ivanov", "Masloyskaya M.N."], [], [], title_source="ocr"))
    batch = await client.post("/api/publication-imports", files={"files": ("scan.pdf", b"%PDF-1.4 ocr authors", "application/pdf")})
    assert batch.status_code == 201
    metadata = batch.json()["items"][0]["extracted_metadata"]
    assert metadata["new_authors"] == []
    assert metadata["unverified_authors"] == ["Masloyskaya M.N."]
