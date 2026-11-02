"""Read-only, memory-safe audit of RescueMesh data files and SQLite DBs."""
import sqlite3, json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".venv", "__pycache__", "node_modules", ".git", ".next", "imagery",
        "srtm", "roads", "frontend", "administrative", "shelters_shp"}
EXT = {".csv", ".json"}
BIG = 40 * 1024 * 1024

def skip(p):
    return any(part in SKIP for part in p.parts) or "\\shelters\\india\\" in str(p)

def audit_db(p):
    print(f"\n=== DB: {p.relative_to(ROOT)} ({p.stat().st_size/1024:.1f} KB)")
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    tabs = [t for (t,) in con.execute("select name from sqlite_master where type='table'")]
    if not tabs: print("  (no tables)")
    for t in tabs:
        n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
        cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
        print(f"  {t}: {n} rows; cols={cols}")
    con.close()

def load(p):
    if p.suffix.lower() == ".csv":
        big = p.stat().st_size > BIG
        df = pd.read_csv(p, low_memory=False, encoding_errors="replace", nrows=200000 if big else None)
        total = None
        if big:
            total = sum(len(c) for c in pd.read_csv(p, usecols=[0], chunksize=500000, encoding_errors="replace"))
        return df, total
    d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    if isinstance(d, dict):
        lists = [v for v in d.values() if isinstance(v, list)]
        d = lists[0] if lists else [d]
    return pd.json_normalize(d), None

def audit_file(p):
    rel = p.relative_to(ROOT)
    if p.stat().st_size == 0:
        print(f"\n--- {rel}: EMPTY"); return
    head = p.read_bytes()[:300].lower().lstrip()
    if head.startswith((b"<html", b"<!doctype", b"<?xml", b'{"error', b"error")):
        print(f"\n--- {rel}: LOOKS LIKE HTML/ERROR, not data. Start: {head[:100]!r}"); return
    try:
        df, total = load(p)
    except Exception as e:
        print(f"\n--- {rel}: UNREADABLE ({type(e).__name__}: {str(e)[:100]})"); return
    note = f" (TOTAL rows={total}; stats below from first {len(df)})" if total else ""
    print(f"\n--- {rel}: {len(df)} rows x {len(df.columns)} cols{note}; dup rows={df.duplicated().sum()}")
    print("  columns:", list(df.columns)[:40])
    nulls = df.isna().mean().round(3)
    print("  worst null fractions:", nulls[nulls > 0].sort_values(ascending=False).head(8).to_dict())
    low = {c.lower(): c for c in df.columns}
    done = False
    for lat in ("latitude", "lat"):
        for lon in ("longitude", "lon", "lng", "long"):
            if lat in low and lon in low and not done:
                la = pd.to_numeric(df[low[lat]], errors="coerce"); lo = pd.to_numeric(df[low[lon]], errors="coerce")
                inside = (la.between(6, 38) & lo.between(68, 98)).mean()
                print(f"  coords: {la.notna().mean():.1%} valid; lat {la.min()}..{la.max()}, lon {lo.min()}..{lo.max()}; inside India bbox {inside:.1%}")
                done = True
    for c in df.columns:
        cl = c.lower()
        if any(k in cl for k in ("date", "time", "year")):
            if pd.api.types.is_numeric_dtype(df[c]):
                print(f"  '{c}' numeric: {df[c].min()} -> {df[c].max()}"); break
            d = pd.to_datetime(df[c], errors="coerce")
            if d.notna().mean() > 0.5:
                print(f"  date col '{c}': {d.min()} -> {d.max()} ({d.isna().mean():.1%} unparseable)"); break

for p in sorted(ROOT.rglob("*")):
    if not p.is_file() or skip(p): continue
    s = p.suffix.lower()
    if s in (".db", ".sqlite", ".sqlite3"): audit_db(p)
    elif s in EXT and "package" not in p.name and "tsconfig" not in p.name: audit_file(p)
