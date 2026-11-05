
import types
import pytest

from fastapi.testclient import TestClient
from backend.app.database import get_db
from backend.app.main import app
from backend.app.security import current_user
from backend.app.services import ingest_runner


@pytest.fixture()
def client(monkeypatch):
    app.dependency_overrides[get_db] = lambda: object()

    monkeypatch.setattr(
        ingest_runner,
        "run_by_key",
        lambda db, key: {
            "source": key,
            "status": "success"
        }
    )

    yield TestClient(app)

    app.dependency_overrides.clear()


def as_role(role):
    app.dependency_overrides[current_user] = lambda: (
        types.SimpleNamespace(
            id=1,
            username="t",
            role=role
        )
    )


def test_coordinator_refreshes_one_source(client):
    as_role("coordinator")

    r = client.post("/live/refresh?source=usgs")

    assert r.status_code == 200
    assert r.json() == {
        "results": [
            {"source": "usgs", "status": "success"}
        ]
    }


def test_default_refreshes_all_sources(client):
    as_role("coordinator")

    assert [
        x["source"]
        for x in client.post("/live/refresh").json()["results"]
    ] == ["usgs", "firms"]


@pytest.mark.parametrize(
    "role",
    ["field_worker", "viewer", "auditor"]
)
def test_non_coordinator_is_forbidden(client, role):
    as_role(role)

    assert client.post("/live/refresh").status_code == 403


def test_unknown_source_is_422(client):
    as_role("coordinator")

    assert client.post(
        "/live/refresh?source=nope"
    ).status_code == 422


def test_requires_login():
    assert TestClient(app).post(
        "/live/refresh"
    ).status_code == 401
