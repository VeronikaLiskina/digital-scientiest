import pytest


async def create_source_file(client, file_name="article.pdf"):
    response = await client.post(
        "/api/source-files",
        json={
            "file_name": file_name,
            "file_path": f"uploads/{file_name}",
            "file_type": "application/pdf",
            "processing_status": "new",
        },
    )

    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_create_processing_log(client):
    source_file = await create_source_file(client)

    response = await client.post(
        "/api/processing-logs",
        json={
            "source_file_id": source_file["id"],
            "step_name": "text_extraction",
            "status": "success",
            "error_message": None,
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["source_file_id"] == source_file["id"]
    assert data["step_name"] == "text_extraction"
    assert data["status"] == "success"
    assert data["error_message"] is None
    assert data["created_at"] is not None


@pytest.mark.asyncio
async def test_get_processing_log_by_id(client):
    source_file = await create_source_file(client)

    create_response = await client.post(
        "/api/processing-logs",
        json={
            "source_file_id": source_file["id"],
            "step_name": "chunking",
            "status": "success",
            "error_message": None,
        },
    )

    log_id = create_response.json()["id"]

    response = await client.get(f"/api/processing-logs/{log_id}")

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == log_id
    assert data["step_name"] == "chunking"
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_get_processing_logs_with_source_file_filter(client):
    first_source_file = await create_source_file(client, file_name="first.pdf")
    second_source_file = await create_source_file(client, file_name="second.pdf")

    await client.post(
        "/api/processing-logs",
        json={
            "source_file_id": first_source_file["id"],
            "step_name": "text_extraction",
            "status": "success",
            "error_message": None,
        },
    )

    await client.post(
        "/api/processing-logs",
        json={
            "source_file_id": second_source_file["id"],
            "step_name": "text_extraction",
            "status": "failed",
            "error_message": "Ошибка обработки",
        },
    )

    response = await client.get(
        "/api/processing-logs",
        params={"source_file_id": first_source_file["id"]},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["source_file_id"] == first_source_file["id"]
    assert data[0]["status"] == "success"


@pytest.mark.asyncio
async def test_update_processing_log(client):
    source_file = await create_source_file(client)

    create_response = await client.post(
        "/api/processing-logs",
        json={
            "source_file_id": source_file["id"],
            "step_name": "embedding",
            "status": "started",
            "error_message": None,
        },
    )

    log_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/processing-logs/{log_id}",
        json={
            "status": "failed",
            "error_message": "Не удалось рассчитать embedding",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == log_id
    assert data["step_name"] == "embedding"
    assert data["status"] == "failed"
    assert data["error_message"] == "Не удалось рассчитать embedding"


@pytest.mark.asyncio
async def test_create_processing_log_with_unknown_source_file_returns_400(client):
    response = await client.post(
        "/api/processing-logs",
        json={
            "source_file_id": 999,
            "step_name": "text_extraction",
            "status": "failed",
            "error_message": "Файл не найден",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Source file not found"


@pytest.mark.asyncio
async def test_delete_processing_log(client):
    source_file = await create_source_file(client)

    create_response = await client.post(
        "/api/processing-logs",
        json={
            "source_file_id": source_file["id"],
            "step_name": "chunking",
            "status": "success",
            "error_message": None,
        },
    )

    log_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/processing-logs/{log_id}")

    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/processing-logs/{log_id}")

    assert get_response.status_code == 404