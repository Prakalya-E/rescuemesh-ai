"""No network: every fetch function below is a fake."""
from datetime import datetime, timedelta, timezone
import pytest
from backend.app import repositories as repo
from backend.app.services import ingest_runner as ir

NOW = datetime.now(timezone.utc)
FIELDS = dict(provider="t", hazard="earthquake", stale_after_minutes=60)


def rec(i, **kw):
    base = dict(external_id=f"e{i}", hazard="earthquake", event_time=NOW - timedelta(hours=1), latitude=20.0,
                longitude=78.0, magnitude=4.5, value=None, unit=None, place="fixture", payload=None)
    base.update(kw)
    return base


@pytest.fixture()
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.database import Base
    from backend.app import models, models_live  # noqa: F401
    eng = create_engine(f"sqlite:///{tmp_path / 'ir.db'}")                # separate test database
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        yield s
    eng.dispose()


def _last_run(db):
    from sqlalchemy import select
    from backend.app.models_live import IngestionRun
    return db.scalar(select(IngestionRun).order_by(IngestionRun.id.desc()))


def test_success_then_duplicate_run_updates_instead_of_adding(db):
    fetch = lambda: ([rec(1), rec(2)], [])
    r1, r2 = ir.run_source(db, "s", FIELDS, fetch), ir.run_source(db, "s", FIELDS, fetch)
    assert (r1["new"], r2["new"], r2["updated"]) == (2, 0, 2)
    assert len(repo.latest_observations(db, "earthquake")) == 2
    assert repo.source_status(db, "s")["status"] == "ok"


def test_invalid_records_are_rejected_but_valid_ones_kept(db):
    r = ir.run_source(db, "s", FIELDS, lambda: ([rec(1), rec(2, latitude=95)], []))
    assert r["new"] == 1 and r["rejected"] == 1


def test_provider_failure_marks_run_failed_and_keeps_old_data(db):
    ir.run_source(db, "s", FIELDS, lambda: ([rec(1)], []))

    def boom():
        raise RuntimeError("provider down")
    r = ir.run_source(db, "s", FIELDS, boom)
    assert r["status"] == "failed" and "provider down" in r["error"]
    assert len(repo.latest_observations(db, "earthquake")) == 1
    assert repo.source_status(db, "s")["status"] == "ok"                 # last success still on record


def test_partial_problems_are_recorded_on_a_successful_run(db):
    r = ir.run_source(db, "s", FIELDS, lambda: ([rec(1)], ["MODIS_NRT: HTTP 503"]))
    assert r["status"] == "success" and r["problems"] == ["MODIS_NRT: HTTP 503"]
    assert "MODIS_NRT" in _last_run(db).error_message


def test_disabled_source_is_skipped(db):
    repo.upsert_source(db, "s", provider="t", hazard="earthquake", enabled=False)
    r = ir.run_source(db, "s", FIELDS, lambda: ([rec(1)], []))
    assert r["status"] == "skipped" and repo.latest_observations(db, "earthquake") == []


def test_error_messages_never_contain_the_api_key(db, monkeypatch):
    monkeypatch.setattr(ir.settings, "FIRMS_MAP_KEY", "SECRETKEY")

    def boom():
        raise RuntimeError("failed for https://x/area/csv/SECRETKEY/y")
    r = ir.run_source(db, "s", FIELDS, boom)
    assert "SECRETKEY" not in r["error"] and "SECRETKEY" not in _last_run(db).error_message


def test_unknown_source_key_is_rejected(db):
    with pytest.raises(ValueError):
        ir.run_by_key(db, "nope")
