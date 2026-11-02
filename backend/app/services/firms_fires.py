"""NASA FIRMS active-fire adapter (area CSV API). Fetching and parsing only; storage is separate.
Needs FIRMS_MAP_KEY. Records are satellite thermal detections: NOT confirmed wildfires, NOT warnings."""
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api"
BOX = "68,6,98,38"  # west,south,east,north. Also covers neighbouring countries, so a polygon filter is used.
PRODUCTS = ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT")
OUTLINE_PATH = (Path(__file__).resolve().parents[3] / "data" / "geospatial" / "processed"
                / "india_outline.geojson")
REQUIRED = {"latitude", "longitude", "acq_date", "acq_time", "confidence", "frp"}
EXTRA = ("satellite", "instrument", "version", "daynight", "confidence", "scan", "track",
         "bright_ti4", "bright_ti5", "brightness", "bright_t31")


class FirmsError(Exception):
    """Missing key/outline, provider failure, or an unusable response. Never contains the API key."""


def fetch_csv(product: str, day_range: int, key: str, timeout: int = 60, http_get=requests.get) -> str:
    if not key:
        raise FirmsError("FIRMS_MAP_KEY is not set")
    if not 1 <= int(day_range) <= 5:
        raise ValueError("day_range must be 1..5")
    url = f"{FIRMS_BASE}/area/csv/{key}/{product}/{BOX}/{int(day_range)}"
    try:
        r = http_get(url, timeout=timeout)
    except requests.RequestException as e:
        raise FirmsError(f"{product}: network error ({type(e).__name__})") from None
    if r.status_code != 200:
        raise FirmsError(f"{product}: HTTP {r.status_code}")
    if not r.text.startswith("latitude"):
        raise FirmsError(f"{product}: response is not a FIRMS CSV")
    return r.text


def confidence_label(raw) -> str:
    """VIIRS gives l/n/h; MODIS gives 0-100 (low <30, nominal 30-79, high >=80)."""
    s = str(raw).strip().lower()
    if s in ("l", "low"):
        return "low"
    if s in ("n", "nominal"):
        return "nominal"
    if s in ("h", "high"):
        return "high"
    try:
        v = float(s)
    except ValueError:
        return "unknown"
    return "low" if v < 30 else "nominal" if v < 80 else "high"


def parse_csv(text: str, product: str, inside=None) -> tuple[list[dict], dict]:
    """CSV text -> repository-ready records. `inside(lat, lon)` is the India polygon test.
    Returns (records, stats) where stats counts rows, outside_india and malformed."""
    reader = csv.DictReader(io.StringIO(text))
    cols = set(reader.fieldnames or [])
    if not REQUIRED <= cols:
        raise FirmsError(f"{product}: missing columns {sorted(REQUIRED - cols)}")
    records, stats = [], {"rows": 0, "outside_india": 0, "malformed": 0}
    for row in reader:
        stats["rows"] += 1
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            hhmm = row["acq_time"].strip().zfill(4)
            when = datetime.strptime(f"{row['acq_date'].strip()} {hhmm}", "%Y-%m-%d %H%M").replace(
                tzinfo=timezone.utc)
            frp = float(row["frp"]) if row["frp"].strip() else None
        except (ValueError, AttributeError, KeyError):
            stats["malformed"] += 1
            continue
        if inside is not None and not inside(lat, lon):
            stats["outside_india"] += 1
            continue
        payload = {k: row[k] for k in EXTRA if row.get(k) not in (None, "")}
        payload.update(product=product, source="NASA FIRMS", confidence_label=confidence_label(row["confidence"]))
        records.append({
            "external_id": f"{product}:{row['acq_date'].strip()}:{hhmm}:{lat:.5f}:{lon:.5f}",
            "hazard": "wildfire", "event_time": when, "latitude": lat, "longitude": lon,
            "magnitude": None, "value": frp, "unit": "MW (FRP)", "place": None, "payload": payload})
    return records, stats


def load_india_filter(path=OUTLINE_PATH):
    """Returns inside(lat, lon) using the India outline built by scripts/build_india_outline.py."""
    path = Path(path)
    if not path.exists():
        raise FirmsError("India outline missing: run scripts/build_india_outline.py first")
    from shapely.geometry import Point, shape
    from shapely.ops import unary_union
    from shapely.prepared import prep
    gj = json.loads(path.read_text(encoding="utf-8"))
    poly = prep(unary_union([shape(f["geometry"]) for f in gj["features"]]))
    return lambda lat, lon: poly.covers(Point(lon, lat))
