"""Keeps live data fresh. Leave this window open, or use --once from Windows Task Scheduler / cron.
    run_scheduler.py                 USGS every 30 min, FIRMS every 120 min
    run_scheduler.py --once          refresh everything once, then exit"""
import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from backend.app.database import Base, SessionLocal, engine
from backend.app import models, models_live  # noqa: F401
from backend.app.services import ingest_runner


def due(last, every_minutes: float, now: float) -> bool:
    return last is None or now - last >= every_minutes * 60


def cycle(key: str):
    with SessionLocal() as db:
        res = ingest_runner.run_by_key(db, key)
    print(f"{datetime.now():%H:%M:%S} {key}: {res}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--usgs-minutes", type=float, default=30)
    ap.add_argument("--firms-minutes", type=float, default=120)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    Base.metadata.create_all(engine)
    if a.once:
        for k in ("usgs", "firms"):
            cycle(k)
        return
    plan = {"usgs": a.usgs_minutes, "firms": a.firms_minutes}
    last = {k: None for k in plan}
    print("scheduler running; press Ctrl+C to stop", flush=True)
    while True:
        now = time.monotonic()
        for k, minutes in plan.items():
            if due(last[k], minutes, now):
                try:
                    cycle(k)
                except Exception as e:                       # one bad cycle must not stop the scheduler
                    print(f"{datetime.now():%H:%M:%S} {k} cycle crashed: {type(e).__name__}", flush=True)
                last[k] = time.monotonic()
        time.sleep(30)


if __name__ == "__main__":
    main()
