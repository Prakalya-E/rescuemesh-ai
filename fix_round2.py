"""Run from D:\\rescuemesh:  python fix_round2.py"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()


def patch(path, pairs):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    for old, new in pairs:
        if new in s:
            continue
        if s.count(old) != 1:
            sys.exit(f"Could not patch {path}: expected 1 match, found {s.count(old)} for:\n{old[:80]}")
        s = s.replace(old, new)
    p.write_text(s, encoding="utf-8")
    print("patched", path)


patch("backend/app/database.py", [
    ("SessionLocal = sessionmaker(bind=engine, autoflush=False)",
     "SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)"),
])

patch("backend/app/services/geo.py", [
    ("MAX_SNAP_KM = 5.0\n",
     'MAX_SNAP_KM = 5.0\nRADIUS = {"hospital": 50.0, "shelter": 80.0, "fire_station": 60.0, "police": 40.0}\n'),
    ("    keep = max(nx.connected_components(G), key=len)\n    G = G.subgraph(keep).copy()\n",
     "    comps = [c for c in nx.connected_components(G) if len(c) >= 100]\n"
     "    if not comps:\n        comps = [max(nx.connected_components(G), key=len)]\n"
     "    G = G.subgraph(set().union(*comps)).copy()\n"),
    ("    fac = load_facilities(kind).copy()\n",
     "    radius_km = radius_km or RADIUS.get(kind, 50.0)\n    fac = load_facilities(kind).copy()\n"),
    ("radius_km: float = 50.0, with_path", "radius_km: float | None = None, with_path"),
    ("    dist = nx.single_source_dijkstra_path_length(G, o_node, weight=\"w\")\n",
     "    dist = nx.single_source_dijkstra_path_length(G, o_node, weight=\"w\")\n"
     "    comp_nodes = np.array(list(nx.node_connected_component(G, o_node)))\n"),
    ("        n, d = _snap(nodes, r.lat, r.lon)\n        if d > MAX_SNAP_KM or n not in dist:",
     "        n, d = _snap(comp_nodes, r.lat, r.lon)\n        if d > MAX_SNAP_KM or n not in dist:"),
])

env = dict(os.environ, PYTHONPATH=str(ROOT))
print("\n=== backend smoke test ===")
rc1 = subprocess.call([sys.executable, "tests/smoke.py"], env=env, cwd=ROOT)
print("\n=== geo test ===")
rc2 = subprocess.call([sys.executable, "tests/geo_test.py"], env=env, cwd=ROOT)
sys.exit(rc1 or rc2)
