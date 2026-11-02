from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import hazards, live
from backend.app.security import current_user


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(hazards.router)
    app.include_router(live.router)
    app.dependency_overrides[current_user] = lambda: object()
    app.dependency_overrides[live.get_db] = lambda: object()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def hazard_table(monkeypatch):
    table = pd.DataFrame([
        {"district": "Cachar", "state_name": "Assam", "hazard": "flood",
         "risk_score": 0.8, "risk_level": "high"},
        {"district": "Kamrup", "state_name": "Assam", "hazard": "flood",
         "risk_score": 0.2, "risk_level": "low"},
        {"district": "Cachar", "state_name": "Assam", "hazard": "wildfire",
         "risk_score": 0.6, "risk_level": "medium"},
    ])
    monkeypatch.setattr(hazards, "long_table", lambda: table)
    return table


def test_hazard_endpoint_filters_and_response_schema(client, hazard_table):
    response = client.get("/hazards/flood?state=Assam&level=high&limit=1")

    assert response.status_code == 200
    assert response.json() == [hazard_table.iloc[0].to_dict()]


def test_hazard_endpoint_returns_empty_list_for_empty_filter(client, hazard_table):
    response = client.get("/hazards/flood?state=Goa")

    assert response.status_code == 200
    assert response.json() == []


def test_hazard_endpoint_reports_unsupported_drought_output(client, hazard_table):
    response = client.get("/hazards/drought")

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown hazard"


def test_live_usgs_endpoint_validates_query_without_network(client, monkeypatch):
    monkeypatch.setattr(live, "fetch_recent_earthquakes", lambda days, min_magnitude: [{
        "external_id": "fixture-1", "hazard": "earthquake",
        "event_time": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "latitude": 28.0, "longitude": 77.0, "magnitude": 4.5,
        "value": None, "unit": None, "place": "fixture",
    }])

    assert client.get("/live/usgs-earthquakes?days=0").status_code == 422
    response = client.get("/live/usgs-earthquakes?days=3&min_magnitude=4.5")

    assert response.status_code == 200
    assert response.json()["observations"][0]["external_id"] == "fixture-1"


def test_stored_observations_endpoint_uses_database_dependency_override(client, monkeypatch):
    stamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    row = SimpleNamespace(
        external_id="stored-1", hazard="earthquake", event_time=stamp, fetched_at=stamp,
        latitude=28.0, longitude=77.0, magnitude=4.5, value=None, unit=None, place="fixture",
    )
    monkeypatch.setattr(live.repo, "latest_observations", lambda db, hazard, limit: [row])

    response = client.get("/live/observations?hazard=earthquake&limit=10")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["observations"][0]["event_time"] == stamp.isoformat()
