"""One-off: light district boundaries for fast lat/lon -> district lookup in the API (the source file is 168 MB)."""
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "geospatial" / "administrative" / "districts" / "district_nwic.GeoJSON"
OUT = ROOT / "data" / "geospatial" / "processed" / "districts_lite.geojson"
HAZ = ROOT / "data" / "processed" / "hazards" / "all_hazards_long.csv"
if OUT.exists():
    sys.exit(f"already exists, not overwriting: {OUT}")

g = gpd.read_file(SRC).to_crs(4326)
missing = [c for c in ("district", "state_name") if c not in g.columns]
if missing:
    sys.exit(f"missing columns {missing}; available: {list(g.columns)}")
lite = g[["district", "state_name", "geometry"]].copy()
lite["geometry"] = lite.geometry.simplify(0.005)          # about 500 m
lite = lite[~lite.geometry.is_empty]
OUT.parent.mkdir(parents=True, exist_ok=True)
lite.to_file(OUT, driver="GeoJSON")
print(f"written: {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f} MB), {len(lite)} polygons")

haz = pd.read_csv(HAZ)[["district", "state_name"]].drop_duplicates()
pairs = lambda df: set(zip(df.district.astype(str), df.state_name.astype(str)))
a, b = pairs(lite), pairs(haz)
print(f"hazard-table districts: {len(b)} | exact (district, state) matches with polygons: {len(a & b)}")
print("in hazard table but no polygon (first 8):", sorted(b - a)[:8])
print("polygons without hazard rows (first 8):", sorted(a - b)[:8])

cities = {"Delhi": (28.61, 77.21), "Chennai": (13.08, 80.27), "Guwahati": (26.14, 91.74),
          "Port Blair": (11.62, 92.73), "Kathmandu (outside India)": (27.70, 85.32)}
pts = gpd.GeoDataFrame({"city": list(cities)}, geometry=gpd.points_from_xy([v[1] for v in cities.values()],
                                                                           [v[0] for v in cities.values()]), crs=4326)
hit = gpd.sjoin(pts, lite, predicate="within", how="left")
for _, r in hit.iterrows():
    print(f"  {r.city:26} -> {r.district}, {r.state_name}")
