from fastapi.testclient import TestClient

from schulmanager_api.main import app

client = TestClient(app)


def _login() -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"email": "demo@example.com", "password": "secret"},
    )
    assert response.status_code == 200
    payload = response.json()
    return {
        "access": payload["access_token"],
        "refresh": payload["refresh_token"],
    }


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_login_and_fetch_students() -> None:
    tokens = _login()
    students_response = client.get(
        "/students",
        headers={"Authorization": f"Bearer {tokens['access']}"},
    )

    assert students_response.status_code == 200
    students = students_response.json()
    assert len(students) >= 1


def test_refresh_token_flow() -> None:
    tokens = _login()
    refresh_response = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh"]},
    )
    assert refresh_response.status_code == 200
    refreshed = refresh_response.json()
    assert refreshed["access_token"]
    assert refreshed["refresh_token"]
    assert refreshed["refresh_token"] != tokens["refresh"]

    replay = client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh"]},
    )
    assert replay.status_code == 401


def test_auth_me() -> None:
    tokens = _login()
    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {tokens['access']}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "demo@example.com"
    assert payload["role"] in {"parent", "admin", "viewer"}


def test_auth_required() -> None:
    response = client.get("/students")
    assert response.status_code == 401
