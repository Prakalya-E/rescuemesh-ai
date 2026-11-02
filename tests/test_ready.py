from fastapi.testclient import TestClient
from backend.app.database import get_db
from backend.app.main import app


class _DbUp:
    def execute(self, *a, **k):
        return 1


class _DbDown:
    def execute(self, *a, **k):
        raise RuntimeError("database unreachable")


def _call(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        return TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.clear()


def test_ready_when_database_and_hazard_tables_exist():
    r = _call(_DbUp())
    assert r.status_code == 200 and r.json() == {"status": "ready", "database": "ok", "hazard_tables": "ok"}


def test_not_ready_when_database_is_down():
    r = _call(_DbDown())
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready" and body["database"].startswith("error")
