"""Run from D:\\rescuemesh:  python setup_geo.py
Adds the geospatial engine (nearest hospitals/shelters/fire/police + road routing)
and a /geo/nearby API endpoint, then runs a test on Cachar and Kamrup (Assam)."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
main_py = ROOT / "backend" / "app" / "main.py"
if not main_py.exists() or "def login" not in main_py.read_text(encoding="utf-8"):
    sys.exit("backend/app/main.py is missing or incomplete. Run  python setup_backend.py  first.")
if not (ROOT / "data" / "processed" / "hazards" / "all_hazards_long.csv").exists():
    sys.exit("data/processed/hazards/all_hazards_long.csv is missing. Run  python ml/combine.py  first.")

FILES = {}

FILES["backend/app/services/geo.py"] = r'''"""Geospatial engine: nearest facilities + road-network routing (NetworkX).

Roads come from the zone shapefiles. Only a window (~0.75 deg each way) around the
origin is read, so the 700 MB files never load whole. Roads are treated as two-way
(emergency vehicles); one-way rules are ignored.
"""
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from pyogrio import read_info

ROOT = Path(__file__).resolve().parents[3]
GEO = ROOT / "data" / "geospatial"
HAZ = ROOT / "data" / "processed" / "hazards"

FAC_FILES = {
    "hospital": GEO / "hospitals" / "osm_hospitals_india.csv",
    "shelter": GEO / "shelters" / "osm_shelters_india.csv",
    "fire_station": GEO / "fire_stations" / "osm_fire_stations_india.csv",
    "police": GEO / "police" / "osm_police_stations_india.csv",
}
SKIP = {"footway", "pedestrian", "steps", "path", "cycleway", "bridleway"}
SPEED = {"motorway": 80, "motorway_link": 50, "trunk": 60, "trunk_link": 40, "primary": 50,
         "primary_link": 35, "secondary": 40, "secondary_link": 30, "tertiary": 30,
         "tertiary_link": 25, "unclassified": 25, "residential": 25, "living_street": 10,
         "service": 15}
OFFROAD_KMH = 20.0
MAX_SNAP_KM = 5.0


def haversine_km(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = (np.sin((lat2 - lat1) * p / 2) ** 2
         + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * np.arcsin(np.sqrt(a))


def _speed(fclass, maxspeed):
    try:
        ms = float(maxspeed)
        if ms > 0:
            return ms
    except (TypeError, ValueError):
        pass
    f = str(fclass)
    if f.startswith("track"):
        return 15.0
    return float(SPEED.get(f, 20))


# ---------------------------------------------------------------- facilities
@lru_cache(maxsize=8)
def load_facilities(kind: str) -> pd.DataFrame:
    if kind not in FAC_FILES:
        raise KeyError(f"Unknown facility kind: {kind}")
    df = pd.read_csv(FAC_FILES[kind], low_memory=False)
    cols = {c.lower(): c for c in df.columns}
    lat = cols.get("latitude") or cols.get("lat") or next(c for l, c in cols.items() if "lat" in l)
    lon = (cols.get("longitude") or cols.get("lon") or cols.get("lng")
           or next(c for l, c in cols.items() if "lon" in l or "lng" in l))
    out = pd.DataFrame({
        "name": df[cols["name"]] if "name" in cols else "",
        "lat": pd.to_numeric(df[lat], errors="coerce"),
        "lon": pd.to_numeric(df[lon], errors="coerce"),
    })
    for extra in ("phone", "address", "state", "operator"):
        if extra in cols:
            out[extra] = df[cols[extra]]
    out = out.dropna(subset=["lat", "lon"])
    out = out[out.lat.between(6, 38) & out.lon.between(67, 98)].reset_index(drop=True)
    out["name"] = out["name"].fillna("").astype(str)
    out.loc[out.name.str.strip() == "", "name"] = f"Unnamed {kind.replace('_', ' ')}"
    return out


# ---------------------------------------------------------------- road zones
@lru_cache(maxsize=1)
def _zones():
    zones = []
    for shp in sorted((GEO / "roads").rglob("gis_osm_roads_free_1.shp")):
        minx, miny, maxx, maxy = read_info(str(shp))["total_bounds"]
        zones.append((str(shp), (minx, miny, maxx, maxy)))
    return zones


def _candidate_zones(lat, lon):
    hits = [(p, b) for p, b in _zones() if b[0] <= lon <= b[2] and b[1] <= lat <= b[3]]
    hits.sort(key=lambda z: (z[1][2] - z[1][0]) * (z[1][3] - z[1][1]))
    return [p for p, _ in hits]


@lru_cache(maxsize=6)
def _graph(zone_path: str, clat: float, clon: float):
    bbox = (clon - 0.75, clat - 0.75, clon + 0.75, clat + 0.75)
    g = gpd.read_file(zone_path, bbox=bbox, engine="pyogrio")
    if g.empty:
        return None
    fclass = g["fclass"] if "fclass" in g.columns else pd.Series([""] * len(g))
    maxspeed = g["maxspeed"] if "maxspeed" in g.columns else pd.Series([0] * len(g))
    G = nx.Graph()
    for geom, fc, ms in zip(g.geometry, fclass, maxspeed):
        if geom is None or fc in SKIP:
            continue
        parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        spd = _speed(fc, ms)
        for ln in parts:
            xy = np.asarray(ln.coords)[:, :2]
            if len(xy) < 2:
                continue
            km = float(haversine_km(xy[:-1, 1], xy[:-1, 0], xy[1:, 1], xy[1:, 0]).sum())
            a = (round(float(xy[0, 1]), 5), round(float(xy[0, 0]), 5))
            b = (round(float(xy[-1, 1]), 5), round(float(xy[-1, 0]), 5))
            if a == b:
                continue
            w = km / spd * 60.0
            if G.has_edge(a, b) and G[a][b]["w"] <= w:
                continue
            G.add_edge(a, b, w=w, km=km, start=a, xy=xy[:, ::-1].tolist())
    if G.number_of_nodes() == 0:
        return None
    keep = max(nx.connected_components(G), key=len)
    G = G.subgraph(keep).copy()
    return G, np.array(list(G.nodes))


def _snap(nodes, lat, lon):
    d = haversine_km(lat, lon, nodes[:, 0], nodes[:, 1])
    i = int(np.argmin(d))
    return (float(nodes[i, 0]), float(nodes[i, 1])), float(d[i])


def _path_info(G, route):
    km, coords = 0.0, []
    for u, v in zip(route[:-1], route[1:]):
        e = G[u][v]
        pts = e["xy"] if e["start"] == u else e["xy"][::-1]
        coords.extend(pts if not coords else pts[1:])
        km += e["km"]
    return km, coords


# ---------------------------------------------------------------- public API
def district_origin(name: str, state: str | None = None):
    t = pd.read_csv(HAZ / "all_hazards_long.csv", usecols=["district", "state_name", "lat", "lon"]).drop_duplicates()
    r = t[t.district.str.lower() == name.lower()]
    if state:
        s = r[r.state_name.str.lower() == state.lower()]
        r = s if not s.empty else r
    if r.empty:
        raise KeyError(f"District not found: {name}")
    return float(r.iloc[0].lat), float(r.iloc[0].lon)


def nearby(lat: float, lon: float, kind: str = "hospital", k: int = 5,
           radius_km: float = 50.0, with_path: bool = False):
    fac = load_facilities(kind).copy()
    fac["straight_km"] = haversine_km(lat, lon, fac.lat.values, fac.lon.values)
    fac = fac[fac.straight_km <= radius_km].nsmallest(max(k * 3, 10), "straight_km")
    result = {"origin": {"lat": lat, "lon": lon}, "kind": kind, "routing": "none",
              "note": "", "results": []}
    if fac.empty:
        result["note"] = f"No {kind.replace('_', ' ')} within {radius_km:.0f} km."
        return result

    G = nodes = o_node = None
    o_off = 0.0
    clat, clon = round(lat * 2) / 2, round(lon * 2) / 2
    for zone in _candidate_zones(lat, lon):
        built = _graph(zone, clat, clon)
        if built is None:
            continue
        G_, nodes_ = built
        n, d = _snap(nodes_, lat, lon)
        if d <= MAX_SNAP_KM:
            G, nodes, o_node, o_off = G_, nodes_, n, d
            break

    if G is None:
        result["note"] = "No road network found near the origin; showing straight-line distances only."
        for _, r in fac.head(k).iterrows():
            result["results"].append({"name": r["name"], "lat": r.lat, "lon": r.lon,
                                      "straight_km": round(r.straight_km, 2), "road_km": None, "eta_min": None})
        return result

    dist = nx.single_source_dijkstra_path_length(G, o_node, weight="w")
    rows = []
    for _, r in fac.iterrows():
        n, d = _snap(nodes, r.lat, r.lon)
        if d > MAX_SNAP_KM or n not in dist:
            continue
        eta = dist[n] + (o_off + d) / OFFROAD_KMH * 60.0
        rows.append((eta, n, d, r))
    rows.sort(key=lambda x: x[0])

    for eta, n, d, r in rows[:k]:
        route = nx.shortest_path(G, o_node, n, weight="w")
        km, coords = _path_info(G, route)
        item = {"name": r["name"], "lat": float(r.lat), "lon": float(r.lon),
                "straight_km": round(float(r.straight_km), 2), "road_km": round(km + o_off + d, 2),
                "eta_min": round(eta, 1)}
        for extra in ("phone", "address"):
            if extra in r.index and pd.notna(r[extra]):
                item[extra] = str(r[extra])
        if with_path:
            item["path"] = coords
        result["results"].append(item)
    result["routing"] = "road_network"
    if not rows:
        result["note"] = "Facilities found but none reachable on the road network."
    return result
'''

FILES["backend/app/routers/geo.py"] = r'''from fastapi import APIRouter, Depends, HTTPException
from ..security import current_user
from ..services import geo

router = APIRouter(prefix="/geo", tags=["geo"], dependencies=[Depends(current_user)])


@router.get("/nearby")
def nearby(kind: str = "hospital", k: int = 5, district: str | None = None, state: str | None = None,
           lat: float | None = None, lon: float | None = None, path: bool = False):
    if kind not in geo.FAC_FILES:
        raise HTTPException(400, f"kind must be one of {sorted(geo.FAC_FILES)}")
    if lat is None or lon is None:
        if not district:
            raise HTTPException(400, "Give either district or lat+lon")
        try:
            lat, lon = geo.district_origin(district, state)
        except KeyError as e:
            raise HTTPException(404, str(e))
    return geo.nearby(lat, lon, kind, k=max(1, min(k, 20)), with_path=path)
'''

FILES["tests/geo_test.py"] = r'''import time
from backend.app.services import geo

for name, state in [("Cachar", "Assam"), ("Kamrup", "Assam")]:
    lat, lon = geo.district_origin(name, state)
    print(f"\n=== {name}, {state} ({lat:.3f}, {lon:.3f})")
    for kind in ["hospital", "shelter", "fire_station"]:
        t = time.time()
        r = geo.nearby(lat, lon, kind, k=3)
        print(f"-- {kind}: routing={r['routing']} {r['note']} ({time.time() - t:.1f}s)")
        for x in r["results"]:
            print(f"   {x['name'][:42]:42} straight={x['straight_km']}km road={x['road_km']}km eta={x['eta_min']}min")
print("\nGEO TEST DONE")
'''

for rel, text in FILES.items():
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    print("wrote", rel)

src = main_py.read_text(encoding="utf-8")
if "geo.router" not in src:
    src = src.replace("from .routers import hazards", "from .routers import hazards, geo")
    src = src.replace("app.include_router(hazards.router)",
                      "app.include_router(hazards.router)\napp.include_router(geo.router)")
    main_py.write_text(src, encoding="utf-8")
    print("patched backend/app/main.py")

print("\nRunning geo test (the first query in an area builds a road graph - allow up to a minute)...\n")
env = dict(os.environ, PYTHONPATH=str(ROOT))
sys.exit(subprocess.call([sys.executable, "tests/geo_test.py"], env=env, cwd=ROOT))
