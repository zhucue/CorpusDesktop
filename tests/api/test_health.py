from fastapi.testclient import TestClient

from services.api.main import CHECKS, app

client = TestClient(app)


def test_liveness_does_not_claim_dependencies_ready():
    assert client.get("/api/v1/health/live").json() == {"status": "alive", "service": "api", "stage": "S1"}


def test_missing_dependencies_are_not_ready(monkeypatch):
    for environment, _ in CHECKS.values():
        monkeypatch.delenv(environment, raising=False)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert all(item["status"] == "not_configured" for item in response.json()["dependencies"].values())


def test_dependency_failure_does_not_leak_connection_secret(monkeypatch):
    def fail(_):
        raise RuntimeError("private-credential")
    monkeypatch.setenv("DATABASE_URL", "private-credential")
    monkeypatch.setitem(CHECKS, "database", ("DATABASE_URL", fail))
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert "private-credential" not in response.text
    assert response.json()["dependencies"]["database"]["status"] == "unavailable"


def test_planned_capabilities_cannot_be_used_as_user_authorization():
    inventory = client.get("/api/v1/system/capabilities").json()
    assert inventory["available"] == []
    assert inventory["planned_count"] > 0
    assert inventory["tool_authorization"] == "production_delegation_not_accepted"
    assert client.get("/api/v1/me/capabilities").status_code == 401


def test_readiness_requires_every_probe(monkeypatch):
    for name, (environment, _) in list(CHECKS.items()):
        monkeypatch.setenv(environment, "fixture")
        monkeypatch.setitem(CHECKS, name, (environment, lambda _: None))
    assert client.get("/api/v1/health/ready").status_code == 200
