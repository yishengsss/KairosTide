from pathlib import Path

from fastapi.testclient import TestClient

from kairos.main import create_app


def test_health_uses_new_temporary_database(tmp_path: Path) -> None:
    database = tmp_path / "new" / "kairos.sqlite3"
    with TestClient(create_app(str(database))) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert database.is_file()


def test_unimplemented_business_route_returns_contract_error(tmp_path: Path) -> None:
    with TestClient(create_app(str(tmp_path / "new.sqlite3"))) as client:
        response = client.get("/api/v1/state")
    assert response.status_code == 501
    payload = response.json()
    assert payload["code"] == "NOT_IMPLEMENTED"
    assert payload["request_id"]
    assert "message" in payload
