"""All CSV text below is a TEST FIXTURE in the real FIRMS column layout, not live data."""
import pytest
from backend.app.services import firms_fires as firms

VIIRS_HEADER = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
VIIRS = (VIIRS_HEADER
         + "28.50000,77.20000,334.5,0.43,0.38,2025-01-10,707,N,VIIRS,n,2.0NRT,297.09,3.16,D\n"
         + "15.98000,97.68000,330.0,0.40,0.40,2025-01-10,1230,N,VIIRS,h,2.0NRT,295.00,5.00,D\n"
         + "abc,77.2,330.0,0.4,0.4,2025-01-10,1230,N,VIIRS,l,2.0NRT,295.00,5.00,D\n")
MODIS = ("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight\n"
         "20.0,78.0,311.4,1.15,1.07,2025-01-10,234,Terra,MODIS,51,6.1NRT,292.5,14.05,D\n"
         "21.0,79.0,311.4,1.15,1.07,2025-01-10,1500,Terra,MODIS,85,6.1NRT,292.5,,N\n"
         "22.0,80.0,311.4,1.15,1.07,2025-01-10,1500,Terra,MODIS,20,6.1NRT,292.5,1.0,N\n")
WEST_OF_90 = lambda lat, lon: lon < 90


def test_parse_viirs_row_fields_and_stats():
    recs, st = firms.parse_csv(VIIRS, "VIIRS_NOAA20_NRT", inside=WEST_OF_90)
    assert st == {"rows": 3, "outside_india": 1, "malformed": 1}
    r = recs[0]
    assert len(recs) == 1 and r["hazard"] == "wildfire"
    assert r["event_time"].isoformat() == "2025-01-10T07:07:00+00:00"      # acq_time "707" -> 07:07 UTC
    assert r["value"] == 3.16 and r["unit"] == "MW (FRP)"
    assert r["payload"]["confidence_label"] == "nominal" and r["payload"]["source"] == "NASA FIRMS"
    assert r["external_id"] == "VIIRS_NOAA20_NRT:2025-01-10:0707:28.50000:77.20000"


def test_modis_numeric_confidence_and_missing_frp():
    recs, _ = firms.parse_csv(MODIS, "MODIS_NRT", inside=None)
    assert [r["payload"]["confidence_label"] for r in recs] == ["nominal", "high", "low"]
    assert recs[1]["value"] is None


def test_ids_are_stable_and_distinct_per_product():
    a, _ = firms.parse_csv(VIIRS, "VIIRS_NOAA20_NRT", inside=WEST_OF_90)
    b, _ = firms.parse_csv(VIIRS, "VIIRS_NOAA20_NRT", inside=WEST_OF_90)
    c, _ = firms.parse_csv(VIIRS, "VIIRS_SNPP_NRT", inside=WEST_OF_90)
    assert a[0]["external_id"] == b[0]["external_id"] != c[0]["external_id"]


def test_missing_columns_rejected():
    with pytest.raises(firms.FirmsError):
        firms.parse_csv("latitude,longitude\n1,2\n", "X")


class Resp:
    def __init__(self, status=200, text=VIIRS):
        self.status_code, self.text = status, text


def test_fetch_requires_key_and_valid_day_range():
    with pytest.raises(firms.FirmsError):
        firms.fetch_csv("MODIS_NRT", 1, "", http_get=lambda *a, **k: Resp())
    with pytest.raises(ValueError):
        firms.fetch_csv("MODIS_NRT", 9, "k", http_get=lambda *a, **k: Resp())


def test_fetch_success_and_url_shape():
    seen = {}

    def get(url, timeout):
        seen["url"], seen["timeout"] = url, timeout
        return Resp()
    assert firms.fetch_csv("MODIS_NRT", 2, "KEY123", timeout=7, http_get=get).startswith("latitude")
    assert seen["url"].endswith("/area/csv/KEY123/MODIS_NRT/68,6,98,38/2") and seen["timeout"] == 7


def test_fetch_errors_never_leak_the_key():
    import requests

    def boom(url, timeout):
        raise requests.ConnectionError(f"failed for {url}")
    with pytest.raises(firms.FirmsError) as e1:
        firms.fetch_csv("MODIS_NRT", 1, "SECRETKEY", http_get=boom)
    assert "SECRETKEY" not in str(e1.value)
    with pytest.raises(firms.FirmsError) as e2:
        firms.fetch_csv("MODIS_NRT", 1, "SECRETKEY", http_get=lambda *a, **k: Resp(503))
    assert "503" in str(e2.value) and "SECRETKEY" not in str(e2.value)
    with pytest.raises(firms.FirmsError):
        firms.fetch_csv("MODIS_NRT", 1, "SECRETKEY", http_get=lambda *a, **k: Resp(200, "Invalid MAP_KEY"))


def test_missing_outline_gives_clear_error(tmp_path):
    with pytest.raises(firms.FirmsError):
        firms.load_india_filter(tmp_path / "nope.geojson")


@pytest.fixture()
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.database import Base
    from backend.app import models, models_live  # noqa: F401
    eng = create_engine(f"sqlite:///{tmp_path / 'f.db'}")      # separate test database
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        yield s
    eng.dispose()


def test_storing_twice_deduplicates(db):
    from backend.app import repositories as repo
    src = repo.upsert_source(db, "nasa_firms_fires", provider="t", hazard="wildfire")
    recs, _ = firms.parse_csv(MODIS, "MODIS_NRT")
    first = [repo.upsert_observation(db, src.id, r) for r in recs]
    second = [repo.upsert_observation(db, src.id, r) for r in recs]
    db.commit()
    assert first == ["new"] * 3 and second == ["updated"] * 3
    assert len(repo.latest_observations(db, "wildfire")) == 3
