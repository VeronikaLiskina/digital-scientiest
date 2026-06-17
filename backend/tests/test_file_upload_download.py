from pathlib import Path

import pytest

from app.core.config import settings


@pytest.mark.asyncio
async def test_upload_pdf_success(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))

    response = await client.post(
        "/api/source-files/upload",
        files={
            "file": (
                "test_article.pdf",
                b"%PDF-1.4\n% test pdf content",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["file_name"] == "test_article.pdf"
    assert data["file_type"] == "application/pdf"
    assert data["processing_status"] == "new"
    assert data["has_figures"] is False
    assert data["has_tables"] is False

    saved_path = Path(data["file_path"])
    assert saved_path.exists()
    assert saved_path.parent == tmp_path


@pytest.mark.asyncio
async def test_upload_non_pdf_returns_400(client):
    response = await client.post(
        "/api/source-files/upload",
        files={
            "file": (
                "notes.txt",
                b"not a pdf",
                "text/plain",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only PDF files are allowed"


@pytest.mark.asyncio
async def test_download_source_file_success(client, tmp_path):
    file_content = b"%PDF-1.4\n% download test content"
    file_path = tmp_path / "download_test.pdf"
    file_path.write_bytes(file_content)

    create_response = await client.post(
        "/api/source-files",
        json={
            "file_name": "download_test.pdf",
            "file_path": str(file_path),
            "file_type": "application/pdf",
            "processing_status": "new",
        },
    )

    assert create_response.status_code == 201

    source_file_id = create_response.json()["id"]

    response = await client.get(f"/api/source-files/{source_file_id}/download")

    assert response.status_code == 200
    assert response.content == file_content
    assert "application/pdf" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_download_missing_file_returns_404(client, tmp_path):
    missing_file_path = tmp_path / "missing.pdf"

    create_response = await client.post(
        "/api/source-files",
        json={
            "file_name": "missing.pdf",
            "file_path": str(missing_file_path),
            "file_type": "application/pdf",
            "processing_status": "new",
        },
    )

    assert create_response.status_code == 201

    source_file_id = create_response.json()["id"]

    response = await client.get(f"/api/source-files/{source_file_id}/download")

    assert response.status_code == 404
    assert response.json()["detail"] == "File not found on server"