"""Fetch recent USGS earthquakes and store them in the live-observation tables."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from backend.app.database import SessionLocal
from backend.app import repositories as repo
from backend.app.models_live import DataSource
from backend.app.services.usgs_earthquakes import fetch_recent_earthquakes


def main():
    with SessionLocal() as db:
        source = db.query(DataSource).filter_by(name="usgs_earthquakes").first()
        if source is None:
            raise RuntimeError(
                "USGS source is not registered. Run scripts/initialize_database.py first."
            )
        if not source.enabled:
            print("USGS source is disabled; ingestion skipped.")
            return

        run = repo.start_run(db, source)
        fetched = new = updated = rejected = 0

        try:
            records = fetch_recent_earthquakes()
            fetched = len(records)

            for record in records:
                try:
                    result = repo.upsert_observation(
                        db, source.id, record, run_id=run.id
                    )
                    if result == "new":
                        new += 1
                    else:
                        updated += 1
                except repo.ObservationError:
                    rejected += 1

            db.commit()
            repo.finish_run(
                db, run, "success",
                records_fetched=fetched,
                records_new=new,
                records_updated=updated,
                records_rejected=rejected,
            )
            print(
                f"USGS ingestion successful: fetched={fetched}, new={new}, "
                f"updated={updated}, rejected={rejected}"
            )

        except Exception as exc:
            db.rollback()
            repo.finish_run(
                db, run, "failed",
                records_fetched=fetched,
                records_new=new,
                records_updated=updated,
                records_rejected=rejected,
                error_message=str(exc)[:2000],
            )
            raise


if __name__ == "__main__":
    main()
