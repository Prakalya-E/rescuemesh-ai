"""Pure-Python geospatial helpers for the API (no GeoPandas needed at request time)."""
import json
import math
from functools import lru_cache
from pathlib import Path

DISTRICTS_LITE = Path(__file__).resolve().parents[3] / "data" / "geospatial" / "processed" / "districts_lite.geojson"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def _in_ring(x: float, y: float, ring) -> bool:
    """Even-odd ray casting."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


class DistrictLocator:
    """lat/lon -> (district, state) using the light boundary file from scripts/build_districts_lite.py."""

    def __init__(self, geojson_path=DISTRICTS_LITE):
        path = Path(geojson_path)
        if not path.exists():
            raise FileNotFoundError(f"{path.name} is missing: run scripts/build_districts_lite.py")
        data = json.loads(path.read_text(encoding="utf-8"))
        self._parts = []        # (minx, miny, maxx, maxy, rings, (district, state))
        for f in data["features"]:
            geom, props = f.get("geometry") or {}, f.get("properties") or {}
            name = (props.get("district"), props.get("state_name"))
            if geom.get("type") == "Polygon":
                polys = [geom["coordinates"]]
            elif geom.get("type") == "MultiPolygon":
                polys = geom["coordinates"]
            else:
                continue
            for rings in polys:
                xs, ys = [pt[0] for pt in rings[0]], [pt[1] for pt in rings[0]]
                self._parts.append((min(xs), min(ys), max(xs), max(ys), rings, name))

    def locate(self, lat: float, lon: float):
        for minx, miny, maxx, maxy, rings, name in self._parts:
            if (minx <= lon <= maxx and miny <= lat <= maxy and _in_ring(lon, lat, rings[0])
                    and not any(_in_ring(lon, lat, hole) for hole in rings[1:])):
                return name
        return None


@lru_cache(maxsize=1)
def get_locator() -> DistrictLocator:
    return DistrictLocator()
