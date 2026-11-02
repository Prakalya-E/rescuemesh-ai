import pytest
from fastapi.testclient import TestClient
from backend.app.database import get_db
from backend.app.main import app
from backend.app.routers import risk
from backend.app.security import current_user


class FakeLocator:
    def locate(self, lat, lon):
        return ("New Delhi", "Delhi") if 28 < lat < 29 else None


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.database import Base
    from backend.app import models, models_live  # noqa: F401
    eng = create_engine(f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False)

    def _db():
        with Session() as s:
            yield s
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[current_user] = lambda: object()
    monkeypatch.setattr(risk, "get_locator", lambda: FakeLocator())
    yield TestClient(app)
    app.dependency_overrides.clear()
    eng.dispose()


def test_predict_returns_structured_assessment(client):
    r = client.post("/risk/predict", json={"latitude": 28.61, "longitude": 77.21})
    assert r.status_code == 200
    b = r.json()
    assert b["location"]["district"] == "New Delhi" and b["location"]["state"] == "Delhi"
    assert {"static_profile", "live_signals", "overall_attention", "interpretation", "live_data_complete"} <= set(b)
    assert b["live_data_complete"] is False                       # no live sources registered in the test database
    assert b["overall_attention"] == "none"


def test_point_outside_any_district_is_404(client):
    assert client.post("/risk/predict", json={"latitude": 20.0, "longitude": 70.0}).status_code == 404


@pytest.mark.parametrize("body", [{"latitude": 50, "longitude": 77}, {"latitude": 28, "longitude": 10},
                                  {"latitude": "abc", "longitude": 77}, {"latitude": 28}])
def test_invalid_input_is_422(client, body):
    assert client.post("/risk/predict", json=body).status_code == 422


def test_requires_login():
    assert TestClient(app).post("/risk/predict", json={"latitude": 28.6, "longitude": 77.2}).status_code == 401
