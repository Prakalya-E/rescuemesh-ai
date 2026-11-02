import numpy as np, pandas as pd, geopandas as gpd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "hazards"
OUT.mkdir(parents=True, exist_ok=True)

def load_districts():
    g = gpd.read_file(ROOT / "data/geospatial/administrative/districts/district_nwic.GeoJSON")
    cols = [c for c in g.columns if c != "geometry"]
    print("District file columns:", cols)
    name = next((c for c in cols if "dist" in c.lower() and "code" not in c.lower()), None)
    state = next((c for c in cols if "stat" in c.lower() and "code" not in c.lower()), None)
    cent = g.to_crs(7755).centroid.to_crs(4326)
    return pd.DataFrame({
        "district": g[name].values if name else np.arange(len(g)).astype(str),
        "state": g[state].values if state else "",
        "state_name": g["state_name"].values if "state_name" in g.columns else "",
        "lat": cent.y.values, "lon": cent.x.values,
    })

def haversine_km(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = np.sin((lat2 - lat1) * p / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(a))

def norm(x):
    x = pd.Series(x, dtype=float)
    return x / x.max() if x.max() > 0 else x

def to_level(score):
    s = pd.Series(score).reset_index(drop=True)
    lv = pd.Series("low", index=s.index)
    pos = s[s > 0]
    if len(pos) >= 4:
        q = pos.quantile([.5, .8, .95]).values
        lv[s > q[0]] = "medium"
        lv[s > q[1]] = "high"
        lv[s > q[2]] = "severe"
    return lv.values


def split_by_target_date(frame, target_date_col, cutoff):
    """Split temporal samples by label time, not the feature timestamp."""
    target_dates = pd.to_datetime(frame[target_date_col], errors="coerce")
    if target_dates.isna().any():
        raise ValueError(f"{target_date_col} contains invalid target dates")
    boundary = pd.Timestamp(cutoff)
    return frame.loc[target_dates < boundary], frame.loc[target_dates >= boundary]


def load_grid(fname, col):
    w = pd.read_csv(ROOT / "data/historical/weather" / fname, usecols=["LAT", "LON", "YEAR", "DOY", col])
    w["date"] = pd.to_datetime(w.YEAR.astype(str) + "-01-01") + pd.to_timedelta(w.DOY - 1, unit="D")
    lats = np.sort(w.LAT.unique()); lons = np.sort(w.LON.unique())
    days = pd.DatetimeIndex(np.sort(w.date.unique()))
    v = w[col].values.astype(np.float32)
    v[v <= -900] = np.nan
    grid = np.full((len(lats), len(lons), len(days)), np.nan, np.float32)
    grid[np.searchsorted(lats, w.LAT.values), np.searchsorted(lons, w.LON.values), days.get_indexer(w.date)] = v
    return lats, lons, days, grid
