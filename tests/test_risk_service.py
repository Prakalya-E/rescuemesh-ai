from datetime import datetime, timedelta, timezone
import pytest
from backend.app.services import risk_service as rs

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
ROWS = [{"hazard": "flood", "risk_score": 0.4, "risk_level": "high"},
        {"hazard": "earthquake", "risk_score": 0.9, "risk_level": "severe"},
        {"hazard": "wildfire", "risk_score": 0.7, "risk_level": "severe"},
        {"hazard": "cyclone", "risk_score": 0.1, "risk_level": "low"}]


def test_profile_marks_old_ml_snapshots_stale_and_sorts_by_level():
    p = rs.static_profile(ROWS, {"flood": "2025-06-30", "wildfire": "2025-06-30"}, NOW)
    by = {x["hazard"]: x for x in p}
    assert by["flood"]["stale"] and by["flood"]["age_days"] > 400
    assert by["earthquake"]["stale"] is False and by["earthquake"]["as_of"] is None
    assert all(x["score_type"] == "relative_rank" for x in p)
    assert p[0]["risk_score"] >= p[1]["risk_score"]                       # severe items first, highest score first


def test_highest_level_ignores_stale_and_under_review_scores():
    p = rs.static_profile(ROWS, {"flood": "2025-06-30", "wildfire": "2025-06-30"}, NOW)
    assert rs.highest_static_level(p) == "severe"                         # from earthquake, not the wildfire model
    only_bad = rs.static_profile([ROWS[0], ROWS[2]], {"flood": "2025-06-30", "wildfire": "2026-10-19"}, NOW)
    assert rs.highest_static_level(only_bad) is None                      # flood stale, wildfire under review


def test_fresh_ml_snapshot_is_not_stale():
    p = rs.static_profile([ROWS[0]], {"flood": "2026-10-18"}, NOW)
    assert p[0]["stale"] is False and rs.highest_static_level(p) == "high"


@pytest.mark.parametrize("n,expected", [(0, "none"), (1, "watch"), (19, "watch"), (20, "elevated"), (500, "elevated")])
def test_fire_attention_thresholds(n, expected):
    assert rs.fire_attention(n) == expected


@pytest.mark.parametrize("m,expected", [(None, "none"), (3.9, "none"), (4.0, "watch"), (5.4, "watch"), (5.5, "elevated")])
def test_quake_attention_thresholds(m, expected):
    assert rs.quake_attention(m) == expected


def test_overall_attention_takes_the_highest():
    assert rs.overall_attention("none", "watch") == "watch"
    assert rs.overall_attention("watch", "elevated", "none") == "elevated"
    assert rs.overall_attention() == "none"


@pytest.fixture()
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.database import Base
    from backend.app import models, models_live  # noqa: F401
    eng = create_engine(f"sqlite:///{tmp_path / 'r.db'}")                 # separate test database
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        yield s
    eng.dispose()


def _add(db, src, ext, hazard, lat, lon, hours_ago, mag=None, conf=None, now=None):
    from backend.app import repositories as repo
    now = now or datetime.now(timezone.utc)
    repo.upsert_observation(db, src.id, {
        "external_id": ext, "hazard": hazard, "event_time": now - timedelta(hours=hours_ago),
        "latitude": lat, "longitude": lon, "magnitude": mag, "value": 3.0, "unit": "x", "place": "fixture",
        "payload": {"confidence_label": conf} if conf else None})


def test_live_signals_apply_radius_window_and_confidence_rules(db):
    from backend.app import repositories as repo
    src = repo.upsert_source(db, "t", provider="p", hazard="mixed")
    _add(db, src, "f1", "wildfire", 20.00, 78.00, 2, conf="nominal")
    _add(db, src, "f2", "wildfire", 20.03, 78.02, 3, conf="high")
    _add(db, src, "f3", "wildfire", 20.01, 78.01, 4, conf="low")          # near but low confidence: ignored
    _add(db, src, "f4", "wildfire", 20.50, 78.00, 2, conf="nominal")      # about 55 km away: ignored
    _add(db, src, "f5", "wildfire", 20.00, 78.00, 30, conf="nominal")     # older than 24 h: ignored
    _add(db, src, "q1", "earthquake", 21.0, 78.0, 10, mag=4.6)            # about 111 km away: counted
    _add(db, src, "q2", "earthquake", 23.0, 78.0, 10, mag=6.1)            # about 333 km away: ignored
    _add(db, src, "q3", "earthquake", 20.2, 78.0, 100, mag=5.9)           # older than 72 h: ignored
    db.commit()
    s = rs.live_signals(db, 20.0, 78.0)
    assert s["wildfire"]["detections_counted"] == 2 and s["wildfire"]["low_confidence_ignored"] == 1
    assert s["wildfire"]["attention"] == "watch" and len(s["wildfire"]["nearest"]) == 2
    assert s["earthquake"]["events_found"] == 1 and s["earthquake"]["attention"] == "watch"
    assert s["earthquake"]["largest"][0]["magnitude"] == 4.6


def test_no_data_gives_none_attention(db):
    s = rs.live_signals(db, 20.0, 78.0)
    assert s["wildfire"]["attention"] == "none" and s["earthquake"]["attention"] == "none"


def test_source_health_flags_unregistered_sources_as_unreliable(db):
    h = rs.source_health(db)
    assert h["wildfire"]["reliable"] is False and h["wildfire"]["status"] == "not_registered"
