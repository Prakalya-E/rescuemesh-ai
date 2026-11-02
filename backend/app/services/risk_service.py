"""Risk lookup and prioritisation for one location.

HOW TO READ THE OUTPUT (these rules are project heuristics, NOT official warnings or probabilities):
* static_profile: per-hazard scores for the district. Scores are RELATIVE RANKS across India's 733 districts.
  'ml' scores are model snapshots with an as_of date; they are marked stale when older than STALE_AFTER_DAYS.
  A score whose status is not 'ok' (e.g. wildfire, under review) is shown but never used for prioritisation.
* highest_static_level: highest level among scores that are status 'ok' and not stale.
* live_signals: recent stored observations near the point, kept separate from the static scores.
    fires (NASA FIRMS):   non-low-confidence detections within 10 km in the last 24 h.
                          0 -> none | 1-19 -> watch | 20 or more -> elevated
    earthquakes (USGS):   largest magnitude within 150 km in the last 72 h.
                          below 4.0 -> none | 4.0-5.4 -> watch | 5.5 or more -> elevated
* overall_attention: the highest live attention level. If a live source is stale or has never succeeded,
  its signal is flagged unreliable, because 'none' could simply mean no fresh data."""
import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .geospatial_service import haversine_km

LEVEL_RANK = {"low": 0, "medium": 1, "high": 2, "severe": 3}
ATTENTION_RANK = {"none": 0, "watch": 1, "elevated": 2}
STALE_AFTER_DAYS = 7
FIRE_RADIUS_KM, FIRE_WINDOW_H, FIRE_WATCH_AT, FIRE_ELEVATED_AT = 10.0, 24, 1, 20
EQ_RADIUS_KM, EQ_WINDOW_H, EQ_WATCH_MAG, EQ_ELEVATED_MAG = 150.0, 72, 4.0, 5.5
INTERPRETATION = ("Scores are relative rankings across districts, not probabilities and not official warnings. "
                  "Live signals are recent satellite/seismic observations from NASA FIRMS and USGS.")

HAZARD_INFO = {
    "flood": dict(method="ml", status="ok", basis="XGBoost ranking trained on IMD-reported flood events and daily "
                  "rainfall; a snapshot of the last weather day in the data, not a forecast"),
    "wildfire": dict(method="ml", status="under_review", basis="next-day fire model under review: training dates "
                     "were found to be altered, so use the live fire detections instead"),
    "earthquake": dict(method="rule_based", status="ok", basis="USGS M4+ events 2000-2024 within 100 km of the "
                       "district centre (frequency and maximum magnitude)"),
    "cyclone": dict(method="rule_based", status="ok", basis="IBTrACS historical storm frequency and intensity"),
    "landslide": dict(method="rule_based", status="ok", basis="NASA landslide catalog 2007-2016; the catalog ends in 2016"),
    "tsunami": dict(method="rule_based", status="ok", basis="NOAA historical tsunami exposure and distance to coast"),
}


def static_profile(rows: list[dict], as_of_by_hazard: dict, now: datetime) -> list[dict]:
    out = []
    for r in rows:
        h = r["hazard"]
        info = HAZARD_INFO.get(h, dict(method="unknown", status="ok", basis=""))
        as_of = as_of_by_hazard.get(h)
        age = (now.date() - datetime.fromisoformat(as_of).date()).days if as_of else None
        stale = info["method"] == "ml" and (age is None or age > STALE_AFTER_DAYS)
        out.append({"hazard": h, "risk_score": float(r["risk_score"]), "risk_level": r["risk_level"],
                    "score_type": "relative_rank", "method": info["method"], "status": info["status"],
                    "basis": info["basis"], "as_of": as_of, "age_days": age, "stale": stale})
    out.sort(key=lambda x: (-LEVEL_RANK.get(x["risk_level"], 0), -x["risk_score"]))
    return out


def highest_static_level(profile: list[dict]):
    ok = [p["risk_level"] for p in profile if p["status"] == "ok" and not p["stale"]]
    return max(ok, key=lambda lv: LEVEL_RANK.get(lv, 0)) if ok else None


def fire_attention(count: int) -> str:
    return "none" if count < FIRE_WATCH_AT else "elevated" if count >= FIRE_ELEVATED_AT else "watch"


def quake_attention(max_mag) -> str:
    if max_mag is None or max_mag < EQ_WATCH_MAG:
        return "none"
    return "elevated" if max_mag >= EQ_ELEVATED_MAG else "watch"


def overall_attention(*levels: str) -> str:
    return max(levels, key=lambda lv: ATTENTION_RANK[lv]) if levels else "none"


def _box(lat: float, lon: float, radius_km: float):
    dlat = radius_km / 111.0
    dlon = dlat / max(math.cos(math.radians(lat)), 0.2)
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def live_signals(db, lat: float, lon: float, now: datetime | None = None) -> dict:
    from sqlalchemy import select
    from ..models_live import LiveObservation as O
    from ..repositories import to_utc
    now = now or datetime.now(timezone.utc)

    la0, la1, lo0, lo1 = _box(lat, lon, FIRE_RADIUS_KM)
    fires = []
    for o in db.scalars(select(O).where(O.hazard == "wildfire", O.event_time >= now - timedelta(hours=FIRE_WINDOW_H),
                                        O.latitude.between(la0, la1), O.longitude.between(lo0, lo1))):
        d = haversine_km(lat, lon, o.latitude, o.longitude)
        if d <= FIRE_RADIUS_KM:
            fires.append((d, o, (o.payload or {}).get("confidence_label", "unknown")))
    counted = sorted((x for x in fires if x[2] != "low"), key=lambda x: x[0])

    la0, la1, lo0, lo1 = _box(lat, lon, EQ_RADIUS_KM)
    quakes = []
    for o in db.scalars(select(O).where(O.hazard == "earthquake", O.event_time >= now - timedelta(hours=EQ_WINDOW_H),
                                        O.latitude.between(la0, la1), O.longitude.between(lo0, lo1))):
        d = haversine_km(lat, lon, o.latitude, o.longitude)
        if d <= EQ_RADIUS_KM and o.magnitude is not None:
            quakes.append((d, o))
    quakes.sort(key=lambda x: -x[1].magnitude)

    return {
        "wildfire": {"attention": fire_attention(len(counted)), "radius_km": FIRE_RADIUS_KM,
                     "window_hours": FIRE_WINDOW_H, "detections_counted": len(counted),
                     "low_confidence_ignored": len(fires) - len(counted),
                     "nearest": [{"distance_km": round(d, 1), "time": to_utc(o.event_time).isoformat(),
                                  "frp_mw": o.value, "confidence": c} for d, o, c in counted[:5]],
                     "note": "Satellite thermal detections: may include agricultural or industrial heat; not confirmed wildfires."},
        "earthquake": {"attention": quake_attention(quakes[0][1].magnitude if quakes else None),
                       "radius_km": EQ_RADIUS_KM, "window_hours": EQ_WINDOW_H, "events_found": len(quakes),
                       "largest": [{"magnitude": o.magnitude, "distance_km": round(d, 1),
                                    "time": to_utc(o.event_time).isoformat(), "place": o.place} for d, o in quakes[:5]],
                       "note": "USGS data; not an official Indian warning."},
    }


def source_health(db) -> dict:
    from .. import repositories as repo
    out = {}
    for key, name in (("wildfire", "nasa_firms_fires"), ("earthquake", "usgs_earthquakes")):
        try:
            s = repo.source_status(db, name)
            out[key] = {"status": s["status"], "last_success": s["last_success"], "reliable": s["status"] == "ok"}
        except KeyError:
            out[key] = {"status": "not_registered", "last_success": None, "reliable": False}
    return out


@lru_cache(maxsize=1)
def _as_of_map() -> dict:
    import pandas as pd
    from ..routers.hazards import OUT
    out = {}
    for h in HAZARD_INFO:
        p = OUT / f"{h}_district.csv"
        if p.exists():
            head = pd.read_csv(p, nrows=1)
            if "as_of" in head.columns and len(head):
                out[h] = str(head["as_of"].iloc[0])
    return out


def district_rows(district: str, state: str) -> list[dict]:
    from ..routers.hazards import long_table
    t = long_table()
    return t[(t.district == district) & (t.state_name == state)].to_dict("records")


def assess(db, lat: float, lon: float, district: str, state: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    profile = static_profile(district_rows(district, state), _as_of_map(), now)
    live = live_signals(db, lat, lon, now)
    health = source_health(db)
    for key in live:
        live[key]["source"] = health[key]
    return {"location": {"latitude": lat, "longitude": lon, "district": district, "state": state},
            "interpretation": INTERPRETATION, "generated_at": now.isoformat(),
            "static_profile": profile, "highest_static_level": highest_static_level(profile),
            "live_signals": live,
            "overall_attention": overall_attention(*(v["attention"] for v in live.values())),
            "live_data_complete": all(h["reliable"] for h in health.values()),
            "warning": None if profile else "no stored hazard scores for this district"}
