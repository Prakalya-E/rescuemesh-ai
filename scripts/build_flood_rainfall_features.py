"""Build a non-destructive, audited 2018 flood rainfall feature extract.

The output path is mandatory and must not already exist. Invalid polygonal
boundaries are repaired in memory only when make_valid preserves planar area
and yields a valid Polygon or MultiPolygon. Unmatched names and rejected
geometry repairs remain as rows with missing features.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re

import geopandas as gpd
import numpy as np
import pandas as pd
from netCDF4 import Dataset, num2date
from shapely import contains_xy, make_valid

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "data/historical/flood/events/India_Flood_Inventory_v3.csv"
MATCH_AUDIT = ROOT / "data/historical/flood/events/flood_2018_district_match_audit.csv"
BOUNDARIES = ROOT / "data/geospatial/administrative/districts/district_nwic.GeoJSON"
RAINFALL = ROOT / "data/environmental/rainfall/RF25_ind2018_rfp25.nc"
OUTPUT_COLUMNS = [
    "UEI", "Start Date", "State Source", "District Source", "Boundary Match",
    "Grid Cells in District", "Start Day Mean Rainfall (mm)",
    "Start Day Valid Coverage (%)", "Previous 3 Days Mean Daily Rainfall (mm)",
    "Previous 3 Days Valid Coverage (%)", "Rainfall Status", "Boundary Geometry Handling",
]


def normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _key(uei: object, date: object, state: object, district: object) -> tuple[str, str, str, str]:
    parsed = pd.to_datetime(date, dayfirst=True, errors="coerce")
    date_key = "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")
    return str(uei), date_key, normalize(state), normalize(district)


def explode_inventory(inventory_path: Path = INVENTORY) -> pd.DataFrame:
    """Expand the 2018 inventory's district lists, retaining source spellings."""
    frame = pd.read_csv(inventory_path, low_memory=False)
    frame["_date"] = pd.to_datetime(frame["Start Date"], dayfirst=True, errors="coerce").dt.normalize()
    frame = frame[frame["_date"].dt.year == 2018].copy()
    frame["_district_list"] = frame["Districts"].fillna(frame.get("Location")).astype(str)
    frame["_district_list"] = frame["_district_list"].str.split(
        r"\s*[,;]\s*|\s+and\s+", regex=True
    )
    frame = frame[["UEI", "Start Date", "State", "_date", "_district_list"]].explode("_district_list")
    frame["District Source"] = frame["_district_list"].astype(str).str.strip()
    frame = frame[frame["District Source"].str.len() > 1]
    return frame.rename(columns={"State": "State Source"})[
        ["UEI", "Start Date", "State Source", "District Source", "_date"]
    ].reset_index(drop=True)


def deduplicate_event_district_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep one row per stable event/date/state/district key, preserving first source spelling."""
    keys = frame.apply(
        lambda r: _key(r["UEI"], r["Start Date"], r["State Source"], r["District Source"]),
        axis=1,
    )
    keep = ~keys.duplicated(keep="first")
    return frame.loc[keep].reset_index(drop=True)


def _crosswalk(frame: pd.DataFrame, audit_path: Path, boundaries_path: Path):
    audit = pd.read_csv(audit_path)
    audit_keys = audit.apply(
        lambda r: _key(r["UEI"], r["Start Date"], r["State"], r["District Source Name"]),
        axis=1,
    )
    inventory_keys = frame.apply(
        lambda r: _key(r["UEI"], r["Start Date"], r["State Source"], r["District Source"]),
        axis=1,
    )
    if Counter(inventory_keys) != Counter(audit_keys):
        raise ValueError("Inventory event-district rows do not reconcile to the local match audit")

    audit = audit.assign(_key=list(audit_keys)).drop_duplicates("_key", keep="first")
    audit_lookup = {row["_key"]: row for _, row in audit.iterrows()}
    polygons = gpd.read_file(boundaries_path).to_crs(4326)
    polygons["_district_key"] = polygons["district"].map(normalize)
    polygons["_state_key"] = polygons["state_name"].map(normalize)
    by_district: dict[str, list[tuple[str, object]]] = {}
    for _, row in polygons.iterrows():
        by_district.setdefault(row["_district_key"], []).append(
            (row["_state_key"], row.geometry)
        )

    matches = []
    for _, row in frame.iterrows():
        key = _key(row["UEI"], row["_date"], row["State Source"], row["District Source"])
        if key not in audit_lookup:
            raise ValueError(f"Missing local district-match audit entry for {key}")
        evidence = audit_lookup[key]
        matched = str(evidence["Boundary Name Match"]).lower() == "true"
        candidates = by_district.get(normalize(evidence["Normalized District"]), []) if matched else []
        state_candidates = [p for p in candidates if p[0] == normalize(row["State Source"])]
        if state_candidates:
            candidates = state_candidates
        if len(candidates) != 1:
            matches.append((matched, None, "District match is ambiguous or unavailable",
                            "Not resolved to a usable polygon"))
            continue
        geometry = candidates[0][1]
        handling = "Source geometry valid"
        if not geometry.is_valid:
            repaired = make_valid(geometry)
            area_unchanged = np.isclose(repaired.area, geometry.area, rtol=1e-9, atol=1e-12)
            polygonal = repaired.geom_type in {"Polygon", "MultiPolygon"}
            if not repaired.is_valid or repaired.is_empty or not polygonal or not area_unchanged:
                matches.append((matched, None, "Invalid district geometry", "Repair rejected"))
                continue
            geometry = repaired
            handling = "Repaired in memory with make_valid; planar area unchanged"
        matches.append((matched, geometry, "", handling))
    return matches


def _read_grid(path: Path):
    with Dataset(path) as dataset:
        lons = np.asarray(dataset.variables["LONGITUDE"][:], dtype=float)
        lats = np.asarray(dataset.variables["LATITUDE"][:], dtype=float)
        variable = dataset.variables["RAINFALL"]
        fill = getattr(variable, "_FillValue", None)
        raw = np.ma.asarray(variable[:], dtype=np.float64)
        rain = np.asarray(np.ma.filled(raw, np.nan))
        if fill is not None:
            rain[rain == float(fill)] = np.nan
        dates = pd.to_datetime([
            str(value) for value in num2date(
                dataset.variables["TIME"][:],
                dataset.variables["TIME"].units,
                only_use_cftime_datetimes=False,
            )
        ]).normalize()
    return lons, lats, dates, rain


def summarize_rainfall_window(
    rain: np.ndarray, mask: np.ndarray, time_index: int
) -> tuple[int, float, float, float, float, str]:
    """Summarize event day and the three preceding days; never uses a future day."""
    cell_count = int(mask.sum())
    if cell_count == 0:
        return cell_count, np.nan, np.nan, np.nan, np.nan, "No grid-cell centres inside district"
    day_values = rain[time_index, mask]
    valid_day = np.isfinite(day_values)
    start_mean = float(day_values[valid_day].mean()) if valid_day.any() else np.nan
    start_coverage = float(100 * valid_day.sum() / cell_count) if valid_day.any() else 0.0
    previous_mean = previous_coverage = np.nan
    if time_index >= 3:
        previous_values = rain[time_index - 3:time_index, mask].reshape(-1)
        valid_previous = np.isfinite(previous_values)
        if valid_previous.any():
            previous_mean = float(previous_values[valid_previous].mean())
            previous_coverage = float(100 * valid_previous.sum() / (3 * cell_count))
        else:
            previous_coverage = 0.0
    status = "Start-day rainfall available" if valid_day.any() else "No valid rainfall on start day"
    return cell_count, start_mean, start_coverage, previous_mean, previous_coverage, status


def generate_features(
    inventory_path: Path = INVENTORY,
    match_audit_path: Path = MATCH_AUDIT,
    boundaries_path: Path = BOUNDARIES,
    rainfall_path: Path = RAINFALL,
) -> tuple[pd.DataFrame, dict[str, int]]:
    expanded = explode_inventory(inventory_path)
    expanded_mapped = _crosswalk(expanded, match_audit_path, boundaries_path)
    keys = expanded.apply(
        lambda r: _key(r["UEI"], r["Start Date"], r["State Source"], r["District Source"]),
        axis=1,
    )
    keep = ~keys.duplicated(keep="first")
    duplicates_removed = int((~keep).sum())
    rows = expanded.loc[keep].reset_index(drop=True)
    mapped = [mapping for mapping, retain in zip(expanded_mapped, keep) if retain]
    lons, lats, dates, rain = _read_grid(rainfall_path)
    if rain.ndim != 3 or rain.shape != (len(dates), len(lats), len(lons)):
        raise ValueError("RF25 variable dimensions do not match its time and coordinate axes")
    date_index = {date: i for i, date in enumerate(dates)}
    xx, yy = np.meshgrid(lons, lats)
    masks: dict[tuple[str, str], np.ndarray] = {}
    output = []

    for (_, source), mapping in zip(rows.iterrows(), mapped):
        matched, geometry, reason, geometry_handling = mapping
        cell_count = np.nan
        start_mean = start_coverage = previous_mean = previous_coverage = np.nan
        if geometry is None:
            status = reason or "District not matched to boundary"
            if status == "District match is ambiguous or unavailable":
                matched = False
            if not geometry_handling:
                geometry_handling = "Not resolved to a usable polygon"
        else:
            mask_key = (str(source["State Source"]), normalize(source["District Source"]))
            if mask_key not in masks:
                masks[mask_key] = contains_xy(geometry, xx, yy)
            mask = masks[mask_key]
            cell_count = int(mask.sum())
            day = pd.to_datetime(source["_date"]).normalize()
            if cell_count == 0:
                status = "No grid-cell centres inside district"
            elif day not in date_index:
                status = "Event date outside rainfall time coverage"
            else:
                ti = date_index[day]
                (cell_count, start_mean, start_coverage, previous_mean,
                 previous_coverage, status) = summarize_rainfall_window(rain, mask, ti)

        output.append({
            "UEI": source["UEI"],
            "Start Date": source["Start Date"],
            "State Source": source["State Source"],
            "District Source": source["District Source"],
            "Boundary Match": bool(matched),
            "Grid Cells in District": cell_count,
            "Start Day Mean Rainfall (mm)": start_mean,
            "Start Day Valid Coverage (%)": start_coverage,
            "Previous 3 Days Mean Daily Rainfall (mm)": previous_mean,
            "Previous 3 Days Valid Coverage (%)": previous_coverage,
            "Rainfall Status": status,
            "Boundary Geometry Handling": geometry_handling,
        })
    result = pd.DataFrame(output, columns=OUTPUT_COLUMNS)
    stats = {
        "inventory_event_district_rows": len(expanded),
        "duplicate_event_district_rows_removed": duplicates_removed,
        "distinct_event_district_rows": len(result),
        "boundary_matched_rows": int(result["Boundary Match"].sum()),
        "rows_with_start_day_rainfall": int(result["Start Day Mean Rainfall (mm)"].notna().sum()),
        "rows_with_complete_required_rainfall": int(
            result[["Start Day Mean Rainfall (mm)",
                    "Previous 3 Days Mean Daily Rainfall (mm)"]].notna().all(axis=1).sum()
        ),
    }
    return result, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="new output CSV path; existing files are never overwritten")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {args.output}")
    result, stats = generate_features()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(stats)
    print(result["Rainfall Status"].value_counts(dropna=False).to_string())
    print(f"Wrote {len(result)} rows to {args.output}")


if __name__ == "__main__":
    main()
