from fastapi.testclient import TestClient


def test_ready_when_database_is_reachable(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
