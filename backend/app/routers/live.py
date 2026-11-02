"""Authenticated API for ingested live observations."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import current_user
from .. import repositories as repo
from ..services.usgs_earthquakes import fetch_recent_earthquakes

router = APIRouter(
    prefix="/live",
    tags=["live"],
    dependencies=[Depends(current_user)],
)


@router.get("/observations")
def get_live_observations(
    hazard: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Return recent stored observations, optionally filtered by hazard."""
    observations = repo.latest_observations(db, hazard=hazard, limit=limit)

    def utc_iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat()

    return {
        "count": len(observations),
        "observations": [
            {
                "external_id": item.external_id,
                "hazard": item.hazard,
                "event_time": utc_iso(item.event_time),
                "fetched_at": utc_iso(item.fetched_at),
                "latitude": item.latitude,
                "longitude": item.longitude,
                "magnitude": item.magnitude,
                "value": item.value,
                "unit": item.unit,
                "place": item.place,
            }
            for item in observations
        ],
    }

@router.get("/usgs-earthquakes")
def get_recent_usgs_earthquakes(
    days: int = Query(default=7, ge=1, le=30),
    min_magnitude: float = Query(default=4.0, ge=0),
):
    """Fetch recent USGS earthquakes without storing them."""
    records = fetch_recent_earthquakes(
        days=days,
        min_magnitude=min_magnitude,
    )

    return {
        "count": len(records),
        "observations": [
            {
                "external_id": item["external_id"],
                "hazard": item["hazard"],
                "event_time": item["event_time"].isoformat(),
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "magnitude": item["magnitude"],
                "value": item["value"],
                "unit": item["unit"],
                "place": item["place"],
            }
            for item in records
        ],
    }



@router.get("/status")
def live_status(db: Session = Depends(get_db)):
    """Health of every registered live source: last success, staleness, newest observation time."""
    from sqlalchemy import select
    from ..models_live import DataSource
    names = [s.name for s in db.scalars(select(DataSource).order_by(DataSource.name))]
    return {"sources": [repo.source_status(db, n) for n in names],
            "note": "Observations keep their original source timestamps. A stale source still serves its last valid data."}


from ..security import require_roles


@router.post("/refresh")
def refresh_live_data(source: str = Query("all", pattern="^(all|usgs|firms)$"),
                      user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    """Admin only: fetch fresh data now. Blocks until finished (typically 10-60 seconds)."""
    from ..services import ingest_runner
    keys = ("usgs", "firms") if source == "all" else (source,)
    return {"results": [ingest_runner.run_by_key(db, k) for k in keys]}
