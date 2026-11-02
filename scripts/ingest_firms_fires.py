"""Fetch recent NASA FIRMS fire detections for India and store them in live_observations."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from backend.app.config import settings
from backend.app.database import Base, SessionLocal, engine
from backend.app import models, models_live  # noqa: F401
from backend.app import repositories as repo
from backend.app.services import firms_fires as firms

SOURCE = "nasa_firms_fires"
DAY_RANGE = 2          # overlap between runs is harmless: duplicates are updated, not added


def main():
    Base.metadata.create_all(engine)          # creates only MISSING tables
    with SessionLocal() as db:
        src = repo.upsert_source(
            db, SOURCE, provider="NASA FIRMS (LANCE near-real-time)", hazard="wildfire",
            base_url=firms.FIRMS_BASE, requires_key=True, stale_after_minutes=360,
            license_note="NASA FIRMS data is open; cite NASA FIRMS. Thermal detections, not confirmed wildfires.")
        if not src.enabled:
            print("FIRMS source is disabled; skipped.")
            return
        run = repo.start_run(db, src)
        fetched = new = upd = rej = 0
        problems, ok_products = [], 0
        try:
            inside = firms.load_india_filter()
            for product in firms.PRODUCTS:
                try:
                    text = firms.fetch_csv(product, DAY_RANGE, settings.FIRMS_MAP_KEY,
                                           timeout=max(settings.HTTP_TIMEOUT_SECONDS, 60))
                    records, st = firms.parse_csv(text, product, inside)
                except firms.FirmsError as e:
                    problems.append(str(e))
                    print("  FAILED:", e)
                    continue
                n0, u0 = new, upd
                for rec in records:
                    try:
                        res = repo.upsert_observation(db, src.id, rec, run_id=run.id)
                        new += res == "new"
                        upd += res == "updated"
                    except repo.ObservationError:
                        rej += 1
                db.commit()
                ok_products += 1
                fetched += st["rows"]
                rej += st["malformed"]
                print(f"  {product}: rows={st['rows']} outside_india={st['outside_india']} "
                      f"malformed={st['malformed']} new={new - n0} updated={upd - u0}")
            status = "success" if ok_products else "failed"
            repo.finish_run(db, run, status, records_fetched=fetched, records_new=new, records_updated=upd,
                            records_rejected=rej, error_message="; ".join(problems)[:2000] or None)
        except firms.FirmsError as e:
            db.rollback()
            repo.finish_run(db, run, "failed", error_message=str(e)[:2000])
            print("FIRMS ingestion failed:", e)
            return
        except Exception as e:
            db.rollback()
            repo.finish_run(db, run, "failed", error_message=f"{type(e).__name__}: {str(e)[:500]}")
            raise
        print(f"FIRMS ingestion {status}: fetched={fetched} new={new} updated={upd} rejected={rej}")
        print("status:", repo.source_status(db, SOURCE))


if __name__ == "__main__":
    main()
