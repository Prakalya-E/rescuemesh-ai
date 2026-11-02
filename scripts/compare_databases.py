"""Read-only: compare the two SQLite files so we know which one the API really uses."""
import sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
for rel in ("rescuemesh.db", r"backend\rescuemesh.db"):
    p = ROOT / rel
    print(f"\n=== {rel}: {'MISSING' if not p.exists() else f'{p.stat().st_size / 1024:.0f} KB'}")
    if not p.exists():
        continue
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    tabs = [t for (t,) in con.execute("select name from sqlite_master where type='table' order by 1")]
    for t in tabs:
        print(f"  {t}: {con.execute(f'select count(*) from \"{t}\"').fetchone()[0]} rows")
    if "ingestion_runs" in tabs:
        for r in con.execute("select id, source_id, started_at, status, records_new, substr(coalesce(error_message,''),1,60) "
                             "from ingestion_runs order by id desc limit 3"):
            print("   run:", r)
    con.close()
