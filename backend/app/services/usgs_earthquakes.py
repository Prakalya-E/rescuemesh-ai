"""USGS earthquake feed adapter. Fetching only; database ingestion is separate."""
from datetime import datetime, timedelta, timezone

import requests

USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
INDIA_BOUNDS = {
    "minlatitude": 6.0,
    "maxlatitude": 38.0,
    "minlongitude": 68.0,
    "maxlongitude": 98.0,
}


def parse_usgs_response(payload: dict) -> list[dict]:
    """Convert a USGS GeoJSON FeatureCollection into repository-ready records."""
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("USGS response is not a GeoJSON FeatureCollection")

    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("USGS response has no valid features list")

    records = []
    for feature in features:
        if not isinstance(feature, dict):
            continue

        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates")

        if not isinstance(coordinates, list) or len(coordinates) < 2:
            continue

        try:
            longitude = float(coordinates[0])
            latitude = float(coordinates[1])
            timestamp = properties["time"]
            event_time = datetime.fromtimestamp(
                float(timestamp) / 1000, tz=timezone.utc
            )
            magnitude = properties.get("mag")
            magnitude = None if magnitude is None else float(magnitude)
            external_id = feature["id"]
            if not external_id:
                continue
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue

        if not (
            INDIA_BOUNDS["minlatitude"] <= latitude <= INDIA_BOUNDS["maxlatitude"]
            and INDIA_BOUNDS["minlongitude"] <= longitude <= INDIA_BOUNDS["maxlongitude"]
        ):
            continue

        records.append({
            "external_id": str(external_id),
            "hazard": "earthquake",
            "event_time": event_time,
            "latitude": latitude,
            "longitude": longitude,
            "magnitude": magnitude,
            "value": None,
            "unit": None,
            "place": properties.get("place"),
            "payload": feature,
        })

    return records


def fetch_recent_earthquakes(
    days: int = 7,
    min_magnitude: float = 4.0,
    timeout: int = 20,
) -> list[dict]:
    """Fetch recent earthquakes in the India-region bounding box."""
    if days < 1:
        raise ValueError("days must be at least 1")
    if min_magnitude < 0:
        raise ValueError("min_magnitude cannot be negative")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    params = {
        "format": "geojson",
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": end.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": min_magnitude,
        **INDIA_BOUNDS,
        "orderby": "time",
    }

    response = requests.get(USGS_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return parse_usgs_response(response.json())
