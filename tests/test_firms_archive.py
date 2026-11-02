"""Fixtures only. No network access."""
from datetime import date
import pytest
from backend.app.services import firms_archive as fa
from backend.app.services.firms_fires import FirmsError

HEAD = "latitude,longitude,acq_date,acq_time\n"


def test_plan_covers_range_exactly_once():
    plan = list(fa.plan_chunks(date(2020, 12, 1), date(2021, 1, 12), 5))
    assert plan[0] == (date(2020, 12, 1), 5) and plan[-1] == (date(2021, 1, 10), 3)
    assert sum(n for _, n in plan) == 43                                  # 31 + 12 days, no gaps/overlaps


def test_plan_rejects_bad_input():
    with pytest.raises(ValueError):
        list(fa.plan_chunks(date(2021, 1, 2), date(2021, 1, 1), 5))
    with pytest.raises(ValueError):
        list(fa.plan_chunks(date(2021, 1, 1), date(2021, 1, 2), 11))


def test_validate_accepts_rows_inside_window():
    assert fa.validate_chunk(HEAD + "1,2,2023-01-01,100\n1,2,2023-01-05,200\n", date(2023, 1, 1), 5) == 2


@pytest.mark.parametrize("body", [HEAD, HEAD + "1,2,2023-01-06,100\n", HEAD + "1,2,not-a-date,100\n", "a,b\n1,2\n"])
def test_validate_rejects_wrong_or_empty_chunks(body):
    with pytest.raises(FirmsError):
        fa.validate_chunk(body, date(2023, 1, 1), 5)


class Resp:
    def __init__(self, status=200, text=HEAD + "1,2,2023-01-01,100\n", js=None):
        self.status_code, self.text, self._js = status, text, js

    def json(self):
        return self._js


def test_fetch_chunk_url_and_error_handling_without_key_leak():
    seen = {}

    def get(url, timeout):
        seen["url"] = url
        return Resp()
    fa.fetch_chunk("VIIRS_SNPP_SP", date(2023, 1, 1), 5, "KEY9", http_get=get)
    assert seen["url"].endswith("/area/csv/KEY9/VIIRS_SNPP_SP/68,6,98,38/5/2023-01-01")
    for bad in (Resp(500), Resp(200, "Invalid MAP_KEY")):
        with pytest.raises(FirmsError) as e:
            fa.fetch_chunk("VIIRS_SNPP_SP", date(2023, 1, 1), 5, "KEY9", http_get=lambda *a, **k: bad)
        assert "KEY9" not in str(e.value)
    with pytest.raises(FirmsError):
        fa.fetch_chunk("VIIRS_SNPP_SP", date(2023, 1, 1), 5, "", http_get=lambda *a, **k: Resp())


def test_transactions_used_reads_meter_and_tolerates_failure():
    assert fa.transactions_used("k", http_get=lambda *a, **k: Resp(200, js={"current_transactions": 12})) == 12

    def boom(*a, **k):
        raise RuntimeError("x")
    assert fa.transactions_used("k", http_get=boom) is None
