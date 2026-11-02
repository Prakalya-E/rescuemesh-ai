"""Create any MISSING tables (existing tables and data are untouched) and seed source metadata."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text
from backend.app.database import Base, engine, SessionLocal
from backend.app import models, models_live  # noqa: F401  (registers tables)
from backend.app import repositories as repo

before = set(inspect(engine).get_table_names())
Base.metadata.create_all(engine)
after = set(inspect(engine).get_table_names())
print("existing tables kept:", sorted(before))
print("tables created now:  ", sorted(after - before))

with SessionLocal() as db:
    repo.upsert_source(db, "usgs_earthquakes", provider="USGS Earthquake Hazards Program",
                       hazard="earthquake", base_url="https://earthquake.usgs.gov/fdsnws/event/1/query",
                       requires_key=False, stale_after_minutes=60,
                       license_note="USGS data is public domain; attribute USGS.")
with engine.connect() as c:
    for t in sorted(after):
        print(f"  {t}: {c.execute(text(f'select count(*) from {t}')).scalar()} rows")
