import time
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
