"""Historical FIRMS archive downloads. Raw CSV chunks only."""
import csv
import io
from datetime import date, timedelta

import requests

from .firms_fires import BOX, FIRMS_BASE, FirmsError

SP_PRODUCT = "VIIRS_SNPP_SP"


def plan_chunks(start: date, end: date, days: int):
    """Cover the date range inclusively without gaps or overlaps."""
    if end < start or not 1 <= days <= 10:
        raise ValueError("need end >= start and 1 <= days <= 10")
    cur = start
    while cur <= end:
        n = min(days, (end - cur).days + 1)
        yield cur, n
        cur += timedelta(days=n)


def fetch_chunk(product: str, start: date, days: int, key: str,
                timeout: int = 120, http_get=requests.get) -> str:
    if not key:
        raise FirmsError("FIRMS_MAP_KEY is not set")
    url = f"{FIRMS_BASE}/area/csv/{key}/{product}/{BOX}/{days}/{start.isoformat()}"
    try:
        response = http_get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise FirmsError(
            f"{product} {start}: network error ({type(exc).__name__})"
        ) from None
    if response.status_code != 200:
        raise FirmsError(f"{product} {start}: HTTP {response.status_code}")
    if not response.text.startswith("latitude"):
        raise FirmsError(f"{product} {start}: response is not a FIRMS CSV")
    return response.text


def validate_chunk(text: str, start: date, days: int) -> int:
    """Return row count; reject empty or out-of-range chunks."""
    reader = csv.DictReader(io.StringIO(text))
    if "acq_date" not in (reader.fieldnames or []):
        raise FirmsError("chunk has no acq_date column")
    end = start + timedelta(days=days - 1)
    count = 0
    for row in reader:
        try:
            acquired = date.fromisoformat(row["acq_date"])
        except (ValueError, TypeError, KeyError):
            raise FirmsError("chunk contains an unreadable acq_date") from None
        if not start <= acquired <= end:
            raise FirmsError(
                f"acq_date {acquired} is outside the requested {start}..{end}"
            )
        count += 1
    if count == 0:
        raise FirmsError("chunk is empty; not saved")
    return count


def transactions_used(key: str, http_get=requests.get):
    """Return FIRMS transaction count, or None if unavailable."""
    if not key:
        return None
    try:
        response = http_get(
            f"{FIRMS_BASE}/mapkey_status/?MAP_KEY={key}", timeout=30
        )
        return (
            int(response.json()["current_transactions"])
            if response.status_code == 200 else None
        )
    except Exception:
        return None
