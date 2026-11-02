"""Evidence-based project cleanup. DRY RUN by default.
With --apply, items are MOVED (never deleted) into D:\\rescuemesh_trash\\<stamp>\\ , keeping their relative
paths, so every step is reversible with --restore <stamp>. Permanent deletion is a separate manual step.

Groups:  junk       caches, partial downloads, a stray duplicate database      (always included)
         duplicates files proven redundant by content checks                    (always included)
         imagery    bulk raw Sentinel bands (quick-look previews are kept)      (--imagery)
         unused     data that no project code references                        (--unused)"""
import argparse
import csv
import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRASH = ROOT.parent / "rescuemesh_trash"
PRUNE = {".venv", ".git", "node_modules", ".next", ".idea", "__pycache__", ".pytest_cache"}
CODE_DIRS = ("backend", "ml", "scripts", "tests", "frontend/src")
SKIP_CODE = ("audit_", "check_", "test_", "cleanup_")


def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def mb(n: int) -> str:
    return f"{n / 1024**3:.2f} GB" if n >= 1024**3 else f"{n / 1024**2:.1f} MB"


def code_texts() -> dict:
    out = {}
    for d in CODE_DIRS:
        for dirpath, dirs, files in os.walk(ROOT / d):
            dirs[:] = [x for x in dirs if x not in PRUNE]
            for fn in files:
                if fn.endswith((".py", ".ts", ".tsx", ".js")) and not fn.startswith(SKIP_CODE):
                    p = Path(dirpath) / fn
                    out[p] = p.read_text(encoding="utf-8", errors="ignore")
    return out


def read_ids(path: Path, col: str) -> set:
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return {row[col] for row in csv.DictReader(f) if col in row}


def zip_matches(zpath: Path, outdir: Path) -> bool:
    """True if every file inside the zip also exists, same size, under outdir (directly or one level down)."""
    with zipfile.ZipFile(zpath) as z:
        for i in z.infolist():
            if i.is_dir():
                continue
            rel = Path(i.filename)
            options = [outdir / rel, outdir / Path(*rel.parts[1:])] if len(rel.parts) > 1 else [outdir / rel]
            if not any(o.is_file() and o.stat().st_size == i.file_size for o in options):
                return False
    return True


def stray_db_ok(stray: Path, main: Path) -> bool:
    if not (stray.is_file() and main.is_file()):
        return False
    a = sqlite3.connect(f"file:{stray}?mode=ro", uri=True)
    b = sqlite3.connect(f"file:{main}?mode=ro", uri=True)
    try:
        tabs = [t for (t,) in a.execute("select name from sqlite_master where type='table'")]
        for t in tabs:
            if t not in ("users", "audit_log") and a.execute(f'select count(*) from "{t}"').fetchone()[0]:
                return False
        mine = {r[0] for r in a.execute("select username from users")} if "users" in tabs else set()
        theirs = {r[0] for r in b.execute("select username from users")}
        return mine <= theirs
    except sqlite3.Error:
        return False
    finally:
        a.close()
        b.close()


def build_plan():
    texts = code_texts()
    items, skipped = [], []

    def add(group, path: Path, reason, tokens=None):
        if not path.exists():
            return
        if tokens:
            hits = sorted({p.relative_to(ROOT).as_posix() for p, t in texts.items() if any(k in t for k in tokens)})
            if hits:
                skipped.append((path, f"still referenced by {hits[:3]}"))
                return
        items.append((group, path, reason))

    for dirpath, dirs, files in os.walk(ROOT):
        for d in list(dirs):
            if d in ("__pycache__", ".pytest_cache") and not any(x in Path(dirpath).parts for x in (".venv", "node_modules", ".git", ".next")):
                add("junk", Path(dirpath) / d, "regenerated automatically")
        dirs[:] = [d for d in dirs if d not in PRUNE]
        for f in files:
            if f.endswith(".part") and "firms_archive" not in dirpath:   # an active download owns these
                add("junk", Path(dirpath) / f, "partial download")
    if stray_db_ok(ROOT / "backend" / "rescuemesh.db", ROOT / "rescuemesh.db"):
        add("junk", ROOT / "backend" / "rescuemesh.db", "stray DB: only users that also exist in the real DB, plus audit rows")
    elif (ROOT / "backend" / "rescuemesh.db").exists():
        skipped.append((ROOT / "backend" / "rescuemesh.db", "contains data not in the main DB; check by hand"))

    ev = ROOT / "data/historical/earthquake/events"
    small, region = ev / "usgs_earthquakes_india_2000_2024.csv", ev / "usgs_earthquakes_india_region_2000_2024.csv"
    if small.exists() and region.exists():
        a, b = read_ids(small, "id"), read_ids(region, "id")
        if a and a <= b:
            add("duplicates", small, "every event ID is also in the region file", ["usgs_earthquakes_india_2000_2024.csv"])
        else:
            skipped.append((small, "IDs unreadable or some are missing from the region file"))
    sh = ROOT / "data/geospatial/shelters"
    main_sh = sh / "osm_shelters_india.csv"
    for name in ("osm_shelters_north_central_east_west.csv", "osm_shelters_southern_india.csv"):
        p = sh / name
        if p.exists() and main_sh.exists():
            a, b = read_ids(p, "osm_id"), read_ids(main_sh, "osm_id")
            if a and a <= b:
                add("duplicates", p, "every osm_id is already in osm_shelters_india.csv", [name])
            else:
                skipped.append((p, "IDs unreadable or some are missing from osm_shelters_india.csv"))
    coast = ROOT / "data/geospatial/coastline/coast.zip"
    if coast.exists():
        if zip_matches(coast, coast.parent):
            add("duplicates", coast, "all contents already extracted beside it", ["coast.zip"])
        else:
            skipped.append((coast, "zip has files that are not extracted"))
    for z in ROOT.glob("data/**/imagery/**/*.SAFE.zip"):
        sd = z.with_suffix("")
        if sd.is_dir() and zip_matches(z, sd):
            add("duplicates", z, "identical files already extracted in the .SAFE folder")
        else:
            skipped.append((z, "extracted folder missing or different"))

    def has_preview(scene: Path):
        return (scene / "preview" / "quick-look.png").exists() or any(scene.glob("*-ql.jpg"))
    for p in ROOT.glob("data/**/imagery/sentinel1/*/*.SAFE/measurement/*.tiff"):
        if has_preview(p.parents[1]):
            add("imagery", p, "raw SAR band; quick-look kept")
        else:
            skipped.append((p, "scene has no quick-look preview"))
    for p in ROOT.glob("data/**/imagery/sentinel2/*/*.SAFE/GRANULE/*/IMG_DATA/*.jp2"):
        if has_preview(p.parents[3]):
            add("imagery", p, "raw optical band; quick-look kept")
        else:
            skipped.append((p, "scene has no quick-look preview"))

    env = ROOT / "data/environmental"
    add("unused", env / "elevation" / "srtm", "no code reads elevation tiles", ["srtm", ".hgt"])
    add("unused", env / "drought_index", "no code reads SPEI files", ["drought_index", "SPEI"])
    for rel, tok in (("data/historical/landslide/events/nasa_global_landslide_catalog.csv", "nasa_global_landslide_catalog"),
                     ("data/historical/tsunami/events/noaa_tsunami_all_events.json", "noaa_tsunami_all_events"),
                     ("data/historical/cyclone/events/ibtracs_north_indian_ocean.csv", "ibtracs_north_indian_ocean")):
        add("unused", ROOT / rel, "global/regional superset; India subset is what the code uses", [tok])
    chosen = sorted({i[1]: i for i in items}.values(), key=lambda i: len(i[1].parts))
    final = []
    for g, p, r in chosen:                                  # drop items nested inside a directory already chosen
        if not any(q in p.parents for _, q, _ in final):
            final.append((g, p, r))
    return final, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--imagery", action="store_true")
    ap.add_argument("--unused", action="store_true")
    ap.add_argument("--restore", metavar="STAMP")
    a = ap.parse_args()
    if a.restore:
        base = TRASH / a.restore
        for rel in json.loads((base / "manifest.json").read_text(encoding="utf-8")):
            src, dest = base / rel, ROOT / rel
            if src.exists() and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                print("restored", rel)
        return
    final, skipped = build_plan()
    on = {"junk", "duplicates"} | ({"imagery"} if a.imagery else set()) | ({"unused"} if a.unused else set())
    totals = {}
    for g in ("junk", "duplicates", "imagery", "unused"):
        rows = [(p, r) for gg, p, r in final if gg == g]
        total = sum(size_of(p) for p, _ in rows)
        totals[g] = total
        print(f"\n== {g.upper()} ({'WILL MOVE' if g in on else 'not selected'}): {len(rows)} item(s), {mb(total)}")
        for p, r in rows[:12]:
            print(f"   {mb(size_of(p)):>10}  {p.relative_to(ROOT).as_posix()}  <- {r}")
        if len(rows) > 12:
            print(f"   ... and {len(rows) - 12} more")
    if skipped:
        print("\n== KEPT (checked, not safe to move):")
        for p, why in skipped[:15]:
            print(f"   {p.relative_to(ROOT).as_posix()}: {why}")
    sel = [(p, r) for g, p, r in final if g in on]
    print(f"\nselected: {len(sel)} item(s), {mb(sum(totals[g] for g in on))}")
    if not a.apply:
        print("DRY RUN - nothing moved. Add --apply to move the selected items to the trash folder.")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    moved = []
    for p, _ in sel:
        rel = p.relative_to(ROOT)
        dest = TRASH / stamp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))
        moved.append(rel.as_posix())
    (TRASH / stamp / "manifest.json").write_text(json.dumps(moved, indent=1), encoding="utf-8")
    print(f"moved {len(moved)} item(s) to {TRASH / stamp}\nundo with: python scripts/cleanup_project.py --restore {stamp}")


if __name__ == "__main__":
    main()
