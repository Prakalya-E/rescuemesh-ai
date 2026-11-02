from datetime import datetime, timezone
from pathlib import Path
import requests
from dotenv import dotenv_values
key = dotenv_values(Path(".env")).get("FIRMS_MAP_KEY", "")
B = "https://firms.modaps.eosdis.nasa.gov/api"
print("UTC now:", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
def get(p):
    try:
        r = requests.get(f"{B}/{p}", timeout=60); return r.status_code, r.text
    except Exception as e:
        return None, type(e).__name__
s, b = get(f"data_availability/csv/{key}/ALL")
print("availability:", s)
print("\n".join(l for l in b.splitlines() if l.startswith("data_id") or "VIIRS" in l or "MODIS" in l) or b[:200])
for src in ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT"):
    for d in (1, 3, 5):
        s, b = get(f"area/csv/{key}/{src}/68,6,98,38/{d}")
        L = b.splitlines() if s == 200 else []
        print(f"{src:17} days={d}: status={s} rows={max(len(L)-1,0)}", "" if s == 200 else b[:80])
        if d == 3 and len(L) > 1: print("   sample:", L[1][:200])
