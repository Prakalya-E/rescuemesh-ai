import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import geo as geo_router
from backend.app.security import current_user


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(geo_router.router)
    app.dependency_overrides[current_user] = lambda: object()
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "query",
    ["lat=91&lon=78", "lat=-91&lon=78", "lat=28&lon=181", "lat=28&lon=-181"],
)
def test_nearby_rejects_coordinates_outside_geographic_ranges(client, query):
    response = client.get(f"/geo/nearby?{query}")

    assert response.status_code == 422


def test_nearby_rejects_partial_coordinate_pair_even_with_district(client):
    response = client.get("/geo/nearby?district=Cachar&state=Assam&lat=26.0")

    assert response.status_code == 400
    assert response.json()["detail"] == "Provide both lat and lon together"


def test_nearby_accepts_complete_pair_and_delegates(client, monkeypatch):
    calls = []

    def fake_nearby(lat, lon, kind, k, with_path):
        calls.append((lat, lon, kind, k, with_path))
        return {"routing": "none", "results": []}

    monkeypatch.setattr(geo_router.geo, "nearby", fake_nearby)
    response = client.get("/geo/nearby?lat=28.6&lon=77.2&kind=hospital&k=4&path=true")

    assert response.status_code == 200
    assert calls == [(28.6, 77.2, "hospital", 4, True)]
