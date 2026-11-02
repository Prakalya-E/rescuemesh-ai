from datetime import datetime, timezone

import pytest
import requests

from backend.app.services import usgs_earthquakes as usgs


def feature(
    event_id="us-test-1",
    longitude=77.2,
    latitude=28.6,
    timestamp=1_750_000_000_000,
    magnitude=4.6,
):
    return {
        "type": "Feature",
        "id": event_id,
        "properties": {
            "time": timestamp,
            "mag": magnitude,
            "place": "Test location, India",
        },
        "geometry": {
            "type": "Point",
            "coordinates": [longitude, latitude, 10.0],
        },
    }


def test_parse_usgs_feature():
    records = usgs.parse_usgs_response({
        "type": "FeatureCollection",
        "features": [feature()],
    })

    assert len(records) == 1
    record = records[0]
    assert record["external_id"] == "us-test-1"
    assert record["hazard"] == "earthquake"
    assert record["latitude"] == 28.6
    assert record["longitude"] == 77.2
    assert record["magnitude"] == 4.6
    assert record["event_time"] == datetime.fromtimestamp(
        1_750_000_000, tz=timezone.utc
    )
    assert record["payload"]["id"] == "us-test-1"


def test_parse_skips_invalid_and_out_of_region_features():
    payload = {
        "type": "FeatureCollection",
        "features": [
            feature(),
            feature(event_id="outside", longitude=120.0, latitude=20.0),
            {"type": "Feature", "id": "missing-geometry",
             "properties": {"time": 1_750_000_000_000}, "geometry": None},
        ],
    }

    records = usgs.parse_usgs_response(payload)
    assert [record["external_id"] for record in records] == ["us-test-1"]


@pytest.mark.parametrize("payload", [
    {},
    {"type": "Feature"},
    {"type": "FeatureCollection", "features": None},
])
def test_parse_rejects_invalid_collection(payload):
    with pytest.raises(ValueError):
        usgs.parse_usgs_response(payload)


def test_fetch_uses_mocked_usgs_response(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "type": "FeatureCollection",
                "features": [feature()],
            }

    captured = {}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(usgs.requests, "get", fake_get)
    records = usgs.fetch_recent_earthquakes(days=3, min_magnitude=4.5)

    assert len(records) == 1
    assert captured["url"] == usgs.USGS_URL
    assert captured["params"]["minmagnitude"] == 4.5
    assert captured["params"]["minlatitude"] == 6.0
    assert captured["timeout"] == 20
    assert captured["params"]["format"] == "geojson"


def test_fetch_propagates_http_error(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            raise requests.HTTPError("mock HTTP failure")

    monkeypatch.setattr(
        usgs.requests, "get", lambda *args, **kwargs: FakeResponse()
    )

    with pytest.raises(requests.HTTPError, match="mock HTTP failure"):
        usgs.fetch_recent_earthquakes()


def test_fetch_rejects_invalid_days():
    with pytest.raises(ValueError, match="days"):
        usgs.fetch_recent_earthquakes(days=0)


def test_fetch_rejects_negative_magnitude():
    with pytest.raises(ValueError, match="min_magnitude"):
        usgs.fetch_recent_earthquakes(min_magnitude=-1)
