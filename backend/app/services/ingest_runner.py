"""One ingestion cycle per source, shared by POST /live/refresh and scripts/run_scheduler.py.
Every cycle writes an ingestion_runs row. A failing source never stops the others and never removes old data."""
from .. import repositories as repo
from ..config import settings
from . import firms_fires as firms
from .usgs_earthquakes import fetch_recent_earthquakes

FIRMS_DAY_RANGE = 2
SOURCES = {
    "usgs": dict(name="usgs_earthquakes", fields=dict(
        provider="USGS Earthquake Hazards Program", hazard="earthquake",
        base_url="https://earthquake.usgs.gov/fdsnws/event/1/query", requires_key=False,
        stale_after_minutes=120, license_note="USGS data is public domain; attribute USGS.")),
    "firms": dict(name="nasa_firms_fires", fields=dict(
        provider="NASA FIRMS (LANCE near-real-time)", hazard="wildfire", base_url=firms.FIRMS_BASE,
        requires_key=True, stale_after_minutes=360,
        license_note="NASA FIRMS data is open; cite NASA FIRMS. Thermal detections, not confirmed wildfires.")),
}


def _clean(message: str) -> str:
    key = settings.FIRMS_MAP_KEY
    return (message.replace(key, "***") if key else message)[:500]


def fetch_usgs():
    return fetch_recent_earthquakes(), []


def fetch_firms():
    inside = firms.load_india_filter()
    records, problems, ok = [], [], 0
    for product in firms.PRODUCTS:
        try:
            text = firms.fetch_csv(product, FIRMS_DAY_RANGE, settings.FIRMS_MAP_KEY,
                                   timeout=max(settings.HTTP_TIMEOUT_SECONDS, 60))
            recs, _ = firms.parse_csv(text, product, inside)
        except firms.FirmsError as e:
            problems.append(str(e))
            continue
        ok += 1
        records += recs
    if not ok:
        raise firms.FirmsError("; ".join(problems) or "no FIRMS product succeeded")
    return records, problems


def run_source(db, name: str, fields: dict, fetch) -> dict:
    """fetch() -> (records, problems). Raises on total failure."""
    src = repo.upsert_source(db, name, **fields)
    run = repo.start_run(db, src)
    if not src.enabled:
        repo.finish_run(db, run, "skipped", error_message="source disabled")
        return {"source": name, "status": "skipped"}
    try:
        records, problems = fetch()
    except Exception as e:
        msg = _clean(f"{type(e).__name__}: {e}")
        repo.finish_run(db, run, "failed", error_message=msg)
        return {"source": name, "status": "failed", "error": msg}
    new = upd = rej = 0
    try:
        for rec in records:
            try:
                res = repo.upsert_observation(db, src.id, rec, run_id=run.id)
                new += res == "new"
                upd += res == "updated"
            except repo.ObservationError:
                rej += 1
        db.commit()
    except Exception as e:
        db.rollback()
        repo.finish_run(db, run, "failed", records_fetched=len(records),
                        error_message=f"database error: {type(e).__name__}")
        return {"source": name, "status": "failed", "error": "database error"}
    repo.finish_run(db, run, "success", records_fetched=len(records), records_new=new, records_updated=upd,
                    records_rejected=rej, error_message=_clean("; ".join(problems)) or None)
    return {"source": name, "status": "success", "fetched": len(records), "new": new, "updated": upd,
            "rejected": rej, "problems": problems}


def run_by_key(db, key: str) -> dict:
    fetchers = {"usgs": fetch_usgs, "firms": fetch_firms}
    if key not in fetchers:
        raise ValueError(f"unknown source {key!r}")
    return run_source(db, SOURCES[key]["name"], SOURCES[key]["fields"], fetchers[key])


def run_all(db) -> list[dict]:
    return [run_by_key(db, k) for k in ("usgs", "firms")]
