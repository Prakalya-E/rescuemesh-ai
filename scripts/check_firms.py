import os, sys
from pathlib import Path
import requests
from dotenv import dotenv_values
key = dotenv_values(Path(".env")).get("FIRMS_MAP_KEY", "")
print("key present:", bool(key), "| length:", len(key))
base = "https://firms.modaps.eosdis.nasa.gov/api"
def get(path):
    try:
        r = requests.get(f"{base}/{path}", timeout=30)
        return r.status_code, r.headers.get("content-type"), r.text
    except Exception as e:
        return None, None, type(e).__name__
s, ct, body = get(f"mapkey_status/?MAP_KEY={key}")
print("mapkey_status:", s, ct, "|", body[:200] if s != 200 or len(body) < 300 else body[:200])
s, ct, body = get(f"area/csv/{key}/VIIRS_SNPP_NRT/68,6,98,38/1")
print("area query:", s, ct)
lines = body.splitlines() if isinstance(body, str) else []
print("first line:", lines[0][:250] if lines else body)
print("data rows:", max(len(lines) - 1, 0))
if len(lines) > 1: print("sample row:", lines[1][:250])
