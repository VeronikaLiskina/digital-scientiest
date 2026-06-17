import pytest


@pytest.mark.asyncio
async def test_create_source_file(client):
    response = await client.post(
        "/api/source-files",
        json={
            "file_name": "article.pdf",
            "file_path": "uploads/article.pdf",
            "file_type": "application/pdf",
            "pdf_quality": "text",
            "has_figures": True,
            "has_tables": False,
            "processing_status": "new",
            "comment": "Тестовый файл",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["file_name"] == "article.pdf"
    assert data["processing_status"] == "new"
    assert data["has_figures"] is True
    assert data["has_tables"] is False


@pytest.mark.asyncio
async def test_get_source_files_with_status_filter(client):
    await client.post(
        "/api/source-files",
        json={
            "file_name": "new_file.pdf",
            "file_path": "uploads/new_file.pdf",
            "file_type": "application/pdf",
            "processing_status": "new",
        },
    )

    await client.post(
        "/api/source-files",
        json={
            "file_name": "processed_file.pdf",
            "file_path": "uploads/processed_file.pdf",
            "file_type": "application/pdf",
            "processing_status": "processed",
        },
    )

    response = await client.get(
        "/api/source-files",
        params={"processing_status": "processed"},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["file_name"] == "processed_file.pdf"
    assert data[0]["processing_status"] == "processed"


@pytest.mark.asyncio
async def test_update_source_file(client):
    create_response = await client.post(
        "/api/source-files",
        json={
            "file_name": "old.pdf",
            "file_path": "uploads/old.pdf",
            "file_type": "application/pdf",
            "processing_status": "new",
        },
    )

    source_file_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/source-files/{source_file_id}",
        json={
            "processing_status": "processed",
            "comment": "Файл обработан",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["processing_status"] == "processed"
    assert data["comment"] == "Файл обработан"


@pytest.mark.asyncio
async def test_delete_source_file(client):
    create_response = await client.post(
        "/api/source-files",
        json={
            "file_name": "delete.pdf",
            "file_path": "uploads/delete.pdf",
            "file_type": "application/pdf",
            "processing_status": "new",
        },
    )

    source_file_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/source-files/{source_file_id}")

    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/source-files/{source_file_id}")

    assert get_response.status_code == 404