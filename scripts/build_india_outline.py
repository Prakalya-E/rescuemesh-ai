"""One-off: build a light India outline from your state boundaries, for point-in-polygon filtering."""
import sys
from pathlib import Path
import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "geospatial" / "administrative" / "states" / "state_NWIC.GeoJSON"
OUT = ROOT / "data" / "geospatial" / "processed" / "india_outline.geojson"
if OUT.exists():
    sys.exit(f"already exists, not overwriting: {OUT}")
g = gpd.read_file(SRC)
if g.crs is None:
    g = g.set_crs(4326)
g = g.to_crs(4326)
outline = g.geometry.simplify(0.005).union_all().buffer(0.02).simplify(0.01)   # ~2 km tolerance at the border
OUT.parent.mkdir(parents=True, exist_ok=True)
gpd.GeoSeries([outline], crs=4326).to_file(OUT, driver="GeoJSON")
print("written:", OUT, f"({OUT.stat().st_size / 1024:.0f} KB)")

from shapely.geometry import Point
checks = {"Delhi": (28.61, 77.21, True), "Chennai": (13.08, 80.27, True), "Guwahati": (26.14, 91.74, True),
          "Port Blair": (11.62, 92.73, True), "Kathmandu": (27.70, 85.32, False), "Dhaka": (23.81, 90.41, False),
          "Colombo": (6.93, 79.86, False), "Yangon": (16.84, 96.17, False), "Karachi": (24.86, 67.01, False)}
bad = 0
for name, (lat, lon, want) in checks.items():
    got = outline.covers(Point(lon, lat))
    bad += got != want
    print(f"  {name:11} inside={got!s:5} expected={want!s:5} {'OK' if got == want else 'MISMATCH'}")
print("all checks OK" if not bad else f"{bad} MISMATCH(ES) - tell me before using this outline")
