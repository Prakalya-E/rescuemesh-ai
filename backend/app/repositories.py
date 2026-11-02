"""Data-access helpers: validation, duplicate-safe inserts, source health."""
import math
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .models_live import DataSource, IngestionRun, LiveObservation

# Crude bounding box around India and nearby areas. Used only as a cheap sanity
# filter. Precise India filtering will use the state/district boundaries.
INDIA_LAT = (6.0, 38.0)
INDIA_LON = (68.0, 98.0)
REQUIRED = ("external_id", "hazard", "event_time", "latitude", "longitude")


class ObservationError(ValueError):
    pass


def to_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; we always store UTC, so naive means UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def validate_observation(rec: dict) -> dict:
    missing = [k for k in REQUIRED if rec.get(k) in (None, "")]
    if missing:
        raise ObservationError(f"missing fields: {missing}")
    try:
        lat, lon = float(rec["latitude"]), float(rec["longitude"])
    except (TypeError, ValueError):
        raise ObservationError("latitude/longitude not numeric")
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ObservationError("latitude/longitude not finite")
    if not (INDIA_LAT[0] <= lat <= INDIA_LAT[1] and INDIA_LON[0] <= lon <= INDIA_LON[1]):
        raise ObservationError("outside India region box")
    t = rec["event_time"]
    if not isinstance(t, datetime):
        raise ObservationError("event_time must be a datetime")
    t = to_utc(t)
    if t > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ObservationError("event_time is in the future")
    out = {"external_id": str(rec["external_id"])[:120], "hazard": str(rec["hazard"]),
           "event_time": t, "latitude": lat, "longitude": lon,
           "unit": rec.get("unit"), "place": (rec.get("place") or None), "payload": rec.get("payload")}
    for k in ("magnitude", "value"):
        try:
            out[k] = None if rec.get(k) is None else float(rec[k])
        except (TypeError, ValueError):
            raise ObservationError(f"{k} not numeric")
    return out


def upsert_source(db: Session, name: str, **fields) -> DataSource:
    src = db.scalar(select(DataSource).where(DataSource.name == name))
    if src is None:
        src = DataSource(name=name, **fields)
        db.add(src)
    else:
        for k, v in fields.items():
            setattr(src, k, v)
    db.commit()
    return src


def start_run(db: Session, source: DataSource) -> IngestionRun:
    run = IngestionRun(source_id=source.id, status="running")
    db.add(run)
    db.commit()
    return run


def finish_run(db: Session, run: IngestionRun, status: str, **fields) -> IngestionRun:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    for k, v in fields.items():
        setattr(run, k, v)
    db.commit()
    return run


def upsert_observation(db: Session, source_id: int, rec: dict, run_id: int | None = None) -> str:
    """Returns 'new' or 'updated'. Raises ObservationError for invalid records.
    Duplicate prevention key: (source_id, external_id). Caller commits."""
    clean = validate_observation(rec)
    obs = db.scalar(select(LiveObservation).where(
        LiveObservation.source_id == source_id,
        LiveObservation.external_id == clean["external_id"]))
    if obs is None:
        db.add(LiveObservation(source_id=source_id, run_id=run_id, **clean))
        db.flush()
        return "new"
    for k, v in clean.items():
        setattr(obs, k, v)
    obs.run_id = run_id
    db.flush()
    return "updated"


def latest_observations(db: Session, hazard: str | None = None, limit: int = 50):
    q = select(LiveObservation).order_by(LiveObservation.event_time.desc()).limit(limit)
    if hazard:
        q = q.where(LiveObservation.hazard == hazard)
    return list(db.scalars(q))


def source_status(db: Session, name: str, now: datetime | None = None) -> dict:
    src = db.scalar(select(DataSource).where(DataSource.name == name))
    if src is None:
        raise KeyError(name)
    now = now or datetime.now(timezone.utc)
    last_ok = db.scalar(select(IngestionRun).where(
        IngestionRun.source_id == src.id, IngestionRun.status == "success")
        .order_by(IngestionRun.finished_at.desc()).limit(1))
    newest = db.scalar(select(func.max(LiveObservation.event_time)).where(LiveObservation.source_id == src.id))
    if last_ok is None or last_ok.finished_at is None:
        status, stale, last_success = "never_succeeded", True, None
    else:
        last_success = to_utc(last_ok.finished_at)
        stale = (now - last_success) > timedelta(minutes=src.stale_after_minutes)
        status = "stale" if stale else "ok"
    return {"source": src.name, "enabled": src.enabled, "status": status, "stale": stale,
            "last_success": last_success.isoformat() if last_success else None,
            "newest_observation_time": to_utc(newest).isoformat() if newest else None,
            "stale_after_minutes": src.stale_after_minutes}


def db_healthcheck(engine) -> bool:
    from sqlalchemy import text
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        return True
    except Exception:
        return False
