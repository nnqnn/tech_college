from fastapi.testclient import TestClient


def test_register_new_user(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users/register",
        json={
            "telegram_id": 123456,
            "username": "test_user",
            "first_name": "Ivan",
            "last_name": "Petrov",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["created"] is True
    assert data["user"]["telegram_id"] == 123456
    assert data["user"]["username"] == "test_user"


def test_register_existing_user(client: TestClient) -> None:
    first = client.post("/api/v1/users/register", json={"telegram_id": 777})
    second = client.post(
        "/api/v1/users/register",
        json={"telegram_id": 777, "first_name": "Alex"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert second.json()["user"]["first_name"] == "Alex"
