import pytest


@pytest.mark.asyncio
async def test_create_author(client):
    response = await client.post(
        "/api/authors",
        json={
            "full_name": "Иванов Иван Иванович",
            "organization": "ИРНИТУ",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["id"] is not None
    assert data["full_name"] == "Иванов Иван Иванович"
    assert data["organization"] == "ИРНИТУ"


@pytest.mark.asyncio
async def test_get_authors_with_search(client):
    await client.post(
        "/api/authors",
        json={
            "full_name": "Иванов Иван Иванович",
            "organization": "ИРНИТУ",
        },
    )
    await client.post(
        "/api/authors",
        json={
            "full_name": "Петров Пётр Петрович",
            "organization": "БГУ",
        },
    )

    response = await client.get("/api/authors", params={"search": "Петров"})

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["full_name"] == "Петров Пётр Петрович"


@pytest.mark.asyncio
async def test_get_author_by_id(client):
    create_response = await client.post(
        "/api/authors",
        json={
            "full_name": "Сидоров Сидор Сидорович",
            "organization": "ИГУ",
        },
    )

    author_id = create_response.json()["id"]

    response = await client.get(f"/api/authors/{author_id}")

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == author_id
    assert data["full_name"] == "Сидоров Сидор Сидорович"


@pytest.mark.asyncio
async def test_update_author(client):
    create_response = await client.post(
        "/api/authors",
        json={
            "full_name": "Старое имя",
            "organization": "Старая организация",
        },
    )

    author_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/authors/{author_id}",
        json={
            "full_name": "Новое имя",
            "organization": "Новая организация",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == author_id
    assert data["full_name"] == "Новое имя"
    assert data["organization"] == "Новая организация"


@pytest.mark.asyncio
async def test_delete_author(client):
    create_response = await client.post(
        "/api/authors",
        json={
            "full_name": "Автор для удаления",
            "organization": "ИРНИТУ",
        },
    )

    author_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/authors/{author_id}")

    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/authors/{author_id}")

    assert get_response.status_code == 404