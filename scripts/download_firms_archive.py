"""Resumable download of historical FIRMS wildfire CSV chunks."""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.config import settings
from backend.app.services import firms_archive as fa
from backend.app.services.firms_fires import FirmsError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", default=fa.SP_PRODUCT)
    parser.add_argument("--start", default="2020-12-01")
    parser.add_argument("--end", default="2025-06-30")
    parser.add_argument("--chunk-days", type=int, default=5)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()

    key = settings.FIRMS_MAP_KEY
    output = ROOT / "data" / "historical" / "wildfire" / "firms_archive" / args.product
    output.mkdir(parents=True, exist_ok=True)

    plan = list(fa.plan_chunks(
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        args.chunk_days,
    ))
    if args.probe:
        plan = [plan[len(plan) // 2]]

    print(f"{args.product}: {len(plan)} chunk(s) -> {output}")
    before = fa.transactions_used(key)
    saved = skipped = rows_total = failures = 0

    for start, days in plan:
        target = output / f"{start.isoformat()}_{days}d.csv"
        if target.exists():
            skipped += 1
            continue

        for attempt in range(3):
            try:
                content = fa.fetch_chunk(args.product, start, days, key)
                rows = fa.validate_chunk(content, start, days)
                temporary = target.with_suffix(".part")
                with open(temporary, "w", encoding="utf-8", newline="") as file:
                    file.write(content)
                temporary.replace(target)
                saved += 1
                rows_total += rows
                failures = 0
                print(f"Saved {target.name}: {rows} rows")
                break
            except FirmsError as exc:
                print(f"Attempt {attempt + 1} failed: {exc}")
                time.sleep(2 ** attempt * 2)
        else:
            failures += 1
            if failures >= 3:
                print("Three consecutive chunks failed; stopping. Re-run to resume.")
                break

        time.sleep(1)

    after = fa.transactions_used(key)
    print(
        f"saved={saved} skipped={skipped} rows={rows_total} "
        f"| FIRMS transactions: {before} -> {after}"
    )


if __name__ == "__main__":
    main()
