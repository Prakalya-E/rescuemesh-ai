from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from backend.app.database import Base
from backend.app import models, models_live  # noqa: F401
from backend.app import repositories as repo
from backend.app.models_live import IngestionRun, LiveObservation

NOW = datetime.now(timezone.utc)


def good(**kw):
    r = dict(external_id="us1", hazard="earthquake", event_time=NOW - timedelta(hours=1),
             latitude=28.6, longitude=77.2, magnitude=4.6, place="test fixture")
    r.update(kw)
    return r


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'test.db'}")   # separate test database
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        yield s
    eng.dispose()


def test_schema_has_expected_tables(db):
    names = set(inspect(db.get_bind()).get_table_names())
    assert {"users", "recommendations", "audit_log", "data_sources", "ingestion_runs",
            "live_observations", "model_versions", "risk_assessments"} <= names


def test_upsert_prevents_duplicates(db):
    src = repo.upsert_source(db, "t", provider="p", hazard="earthquake")
    assert repo.upsert_observation(db, src.id, good()) == "new"
    assert repo.upsert_observation(db, src.id, good(magnitude=4.9)) == "updated"
    db.commit()
    rows = repo.latest_observations(db)
    assert len(rows) == 1 and rows[0].magnitude == 4.9


@pytest.mark.parametrize("bad", [
    dict(latitude=95), dict(latitude=-10), dict(longitude=150), dict(latitude="abc"),
    dict(external_id=None), dict(event_time=NOW + timedelta(days=2)), dict(latitude=float("nan")),
])
def test_invalid_records_rejected(db, bad):
    src = repo.upsert_source(db, "t", provider="p", hazard="earthquake")
    with pytest.raises(repo.ObservationError):
        repo.upsert_observation(db, src.id, good(**bad))


def test_db_level_unique_constraint(db):
    src = repo.upsert_source(db, "t", provider="p", hazard="earthquake")
    for _ in range(2):
        db.add(LiveObservation(source_id=src.id, external_id="x", hazard="earthquake",
                               event_time=NOW, latitude=20, longitude=78))
    with pytest.raises(IntegrityError):
        db.commit()


def test_source_never_succeeded_is_stale(db):
    repo.upsert_source(db, "t", provider="p", hazard="earthquake", stale_after_minutes=60)
    s = repo.source_status(db, "t")
    assert s["status"] == "never_succeeded" and s["stale"] is True


def test_source_stale_vs_fresh(db):
    src = repo.upsert_source(db, "t", provider="p", hazard="earthquake", stale_after_minutes=60)
    run = repo.start_run(db, src)
    repo.finish_run(db, run, "success")
    assert repo.source_status(db, "t")["status"] == "ok"
    later = datetime.now(timezone.utc) + timedelta(hours=3)
    assert repo.source_status(db, "t", now=later)["stale"] is True


def test_failed_run_does_not_count_as_success(db):
    src = repo.upsert_source(db, "t", provider="p", hazard="earthquake")
    repo.finish_run(db, repo.start_run(db, src), "failed", error_message="timeout")
    assert repo.source_status(db, "t")["status"] == "never_succeeded"
