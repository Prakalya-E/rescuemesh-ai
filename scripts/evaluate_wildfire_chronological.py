"""Run a read-only chronological wildfire model evaluation.

This evaluator reproduces the feature construction in ml/risk_wildfire.py but
never writes or loads a model artifact or processed prediction file. Output is
mandatory and must be a new file path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ["tmax", "rain7", "rain30", "dry_days", "fire7", "fire30", "lat", "lon", "msin", "mcos"]


def load_districts() -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    polygons = gpd.read_file(ROOT / "data/geospatial/administrative/districts/district_nwic.GeoJSON")
    polygons = polygons.to_crs(4326)
    centers = polygons.to_crs(7755).centroid.to_crs(4326)
    return pd.DataFrame({
        "district": polygons["district"].to_numpy(),
        "state_name": polygons["state_name"].to_numpy(),
        "lat": centers.y.to_numpy(),
        "lon": centers.x.to_numpy(),
    }), polygons[["geometry"]]


def load_grid(filename: str, column: str):
    weather = pd.read_csv(ROOT / "data/historical/weather" / filename,
                          usecols=["LAT", "LON", "YEAR", "DOY", column])
    weather["date"] = pd.to_datetime(weather.YEAR.astype(str) + "-01-01") + pd.to_timedelta(weather.DOY - 1, unit="D")
    lats, lons = np.sort(weather.LAT.unique()), np.sort(weather.LON.unique())
    days = pd.DatetimeIndex(np.sort(weather.date.unique()))
    values = weather[column].to_numpy(dtype=np.float32)
    values[values <= -900] = np.nan
    grid = np.full((len(lats), len(lons), len(days)), np.nan, np.float32)
    grid[np.searchsorted(lats, weather.LAT), np.searchsorted(lons, weather.LON), days.get_indexer(weather.date)] = values
    return lats, lons, days, grid


def rolling_sum(matrix: np.ndarray, width: int) -> np.ndarray:
    cumulative = np.cumsum(matrix, axis=1)
    result = cumulative.copy()
    result[:, width:] = cumulative[:, width:] - cumulative[:, :-width]
    return result


def build_frame() -> tuple[pd.DataFrame, int, int]:
    districts, polygons = load_districts()
    detections = pd.read_csv(ROOT / "data/historical/wildfire/events/wildfire_detections_clean.csv",
                             usecols=["Date", "Lon", "Lat"])
    detections["Date"] = pd.to_datetime(detections.Date, errors="coerce")
    detections = detections.dropna()
    points = gpd.GeoDataFrame({"date": detections.Date.to_numpy()},
                              geometry=gpd.points_from_xy(detections.Lon, detections.Lat), crs=4326)
    joined = gpd.sjoin(points, polygons, predicate="within", how="inner")
    joined = joined[~joined.index.duplicated()]
    joined["di"] = joined.index_right
    # NWIC feature IDs may not be a zero-based contiguous index; map the joined
    # right index back to the positional ordering used for district rows.
    pos = {idx: i for i, idx in enumerate(polygons.index)}
    joined["di"] = joined.index_right.map(pos).astype(int)

    lats, lons, days, tmax = load_grid("nasa_T2M_MAX_20201201_20250630.csv", "T2M_MAX")
    _, _, pr_days, rain = load_grid("nasa_PRECTOTCORR_20201201_20250630.csv", "PRECTOTCORR")
    if not days.equals(pr_days):
        raise ValueError("Weather grids have different daily axes")
    rain = np.nan_to_num(rain, nan=0.0)
    rain[rain < 0] = 0
    district_count, day_count = len(districts), len(days)
    counts = np.zeros((district_count, day_count), np.float32)
    time_index = days.get_indexer(pd.DatetimeIndex(joined.date))
    valid = time_index >= 0
    np.add.at(counts, (joined.di.to_numpy()[valid], time_index[valid]), 1)
    lat_ix = np.abs(lats[None, :] - districts.lat.to_numpy()[:, None]).argmin(axis=1)
    lon_ix = np.abs(lons[None, :] - districts.lon.to_numpy()[:, None]).argmin(axis=1)
    rain_district = rain[lat_ix, lon_ix, :]
    tmax_district = tmax[lat_ix, lon_ix, :]

    dry_days = np.zeros_like(rain_district)
    run = np.zeros(district_count, np.float32)
    for day in range(day_count):
        run = np.where(rain_district[:, day] > 1, 0, run + 1)
        dry_days[:, day] = run
    features = {
        "tmax": tmax_district,
        "rain7": rolling_sum(rain_district, 7),
        "rain30": rolling_sum(rain_district, 30),
        "dry_days": dry_days,
        "fire7": rolling_sum(counts, 7),
        "fire30": rolling_sum(counts, 30),
    }
    # A row's predictors are available at the end of its feature date; its
    # label is the following day. Exclude the first 30 days for full windows.
    feature_days = np.arange(30, day_count - 1)
    n = len(feature_days)
    frame = pd.DataFrame({name: values[:, feature_days].ravel() for name, values in features.items()})
    frame["lat"] = np.repeat(districts.lat.to_numpy(), n)
    frame["lon"] = np.repeat(districts.lon.to_numpy(), n)
    doy = np.tile(days[feature_days].dayofyear.to_numpy(), district_count)
    frame["msin"] = np.sin(2 * np.pi * doy / 365.25)
    frame["mcos"] = np.cos(2 * np.pi * doy / 365.25)
    frame["target_date"] = np.tile(days[feature_days + 1].to_numpy(), district_count)
    frame["y"] = (counts[:, feature_days + 1].ravel() >= 3).astype(np.uint8)
    frame["fire7"] = features["fire7"][:, feature_days].ravel()
    return frame, len(detections), len(joined)


def block_bootstrap_delta(y: np.ndarray, model_score: np.ndarray, baseline_score: np.ndarray,
                          dates: np.ndarray, seed: int, n_bootstrap: int = 100) -> dict:
    unique_dates = pd.DatetimeIndex(pd.to_datetime(dates)).unique().sort_values()
    if len(unique_dates) < 60:
        return {"method": "30-day contiguous date-block bootstrap", "replicates": 0,
                "reason": "test set contains fewer than 60 dates"}
    # Contiguous blocks preserve short-term temporal dependence. The final
    # partial block is retained as its actual length.
    date_to_block = {date: i // 30 for i, date in enumerate(unique_dates)}
    blocks = np.array([date_to_block[pd.Timestamp(date)] for date in pd.to_datetime(dates)])
    block_ids = np.arange(int(blocks.max()) + 1)
    rows_by_block = [np.flatnonzero(blocks == block) for block in block_ids]
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(n_bootstrap):
        picked = rng.choice(block_ids, size=len(block_ids), replace=True)
        ix = np.concatenate([rows_by_block[block] for block in picked])
        if len(np.unique(y[ix])) < 2:
            continue
        deltas.append(average_precision_score(y[ix], model_score[ix]) -
                      average_precision_score(y[ix], baseline_score[ix]))
    if not deltas:
        return {"method": "30-day contiguous date-block bootstrap", "replicates": 0,
                "reason": "no bootstrap sample contained both classes"}
    return {"method": "30-day contiguous date-block bootstrap", "replicates": len(deltas),
            "seed": seed, "delta_average_precision_95pct_percentile_ci": [
                float(np.quantile(deltas, .025)), float(np.quantile(deltas, .975))]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="new JSON evidence path; existing files are never overwritten")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap", type=int, default=100)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite existing output: {args.output}")

    frame, detection_count, joined_count = build_frame()
    targets = pd.to_datetime(frame.target_date)
    train = frame.loc[targets < "2023-01-01"]
    validation = frame.loc[(targets >= "2023-01-01") & (targets < "2024-01-01")]
    test = frame.loc[targets >= "2024-01-01"]
    if train.y.nunique() != 2 or test.y.nunique() != 2:
        raise ValueError("Train or test partition does not contain both target classes")

    model = XGBClassifier(n_estimators=300, max_depth=6, learning_rate=.06,
                          subsample=.8, colsample_bytree=.8,
                          scale_pos_weight=min(20, (train.y == 0).sum() / max(int(train.y.sum()), 1)),
                          eval_metric="aucpr", n_jobs=1, random_state=args.seed)
    model.fit(train[FEATURES], train.y)
    model_score = model.predict_proba(test[FEATURES])[:, 1]
    persistence = test.fire7.to_numpy(dtype=float)
    y = test.y.to_numpy(dtype=int)
    test_dates = pd.to_datetime(test.target_date).to_numpy()
    result = {
        "protocol": "train target dates < 2023-01-01; validation 2023; untouched test target dates >= 2024-01-01",
        "feature_timing": "features through feature_date predict next-day target_date; first 30 days excluded for complete rolling windows",
        "seed": args.seed,
        "model": {"class": "XGBClassifier", "n_estimators": 300, "max_depth": 6,
                  "learning_rate": .06, "subsample": .8, "colsample_bytree": .8,
                  "n_jobs": 1, "random_state": args.seed},
        "baseline": "persistence score = count of fire detections during preceding 7 feature days (fire7); no test labels used for fitting",
        "source_events": {"valid_rows": detection_count, "joined_to_districts": joined_count},
        "partitions": {"train_rows": len(train), "train_positive": int(train.y.sum()),
                       "validation_rows": len(validation), "validation_positive": int(validation.y.sum()),
                       "test_rows": len(test), "test_positive": int(y.sum()),
                       "test_positive_rate": float(y.mean()),
                       "test_target_date_min": str(pd.to_datetime(test_dates).min().date()),
                       "test_target_date_max": str(pd.to_datetime(test_dates).max().date())},
        "test_metrics": {
            "model_roc_auc": float(roc_auc_score(y, model_score)),
            "model_average_precision": float(average_precision_score(y, model_score)),
            "persistence_roc_auc": float(roc_auc_score(y, persistence)),
            "persistence_average_precision": float(average_precision_score(y, persistence)),
            "prevalence_reference_average_precision": float(y.mean()),
        },
        "uncertainty": block_bootstrap_delta(y, model_score, persistence, test_dates,
                                             args.seed, args.bootstrap),
        "limitations": [
            "Evaluation trains a fresh model and does not validate or deserialize the existing joblib artifact.",
            "Validation-year records are reported but not used for model selection or threshold tuning.",
            "Block-bootstrap interval is a temporal sampling estimate; it does not address label/source bias, spatial transfer, or calibration.",
            "Features and event-to-district assignment reproduce the current training pipeline and inherit its source-data limitations.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
