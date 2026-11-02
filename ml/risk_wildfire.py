import json, numpy as np, pandas as pd, geopandas as gpd, joblib
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score, average_precision_score
from common import *

d = load_districts(); nd = len(d)
g = gpd.read_file(ROOT / "data/geospatial/administrative/districts/district_nwic.GeoJSON").to_crs(4326)[["geometry"]]
g["di"] = np.arange(len(g))

f = pd.read_csv(ROOT / "data/historical/wildfire/events/wildfire_detections_clean.csv", usecols=["Date", "Lon", "Lat"])
f["Date"] = pd.to_datetime(f.Date, errors="coerce")
f = f.dropna()
pts = gpd.GeoDataFrame({"date": f.Date.values}, geometry=gpd.points_from_xy(f.Lon, f.Lat), crs=4326)
j = gpd.sjoin(pts, g, predicate="within", how="inner")
j = j[~j.index.duplicated()]
print("detections inside district polygons:", len(j), "of", len(f))

lats, lons, days, TX = load_grid("nasa_T2M_MAX_20201201_20250630.csv", "T2M_MAX")
_, _, _, PR = load_grid("nasa_PRECTOTCORR_20201201_20250630.csv", "PRECTOTCORR")
PR = np.nan_to_num(PR, nan=0.0); PR[PR < 0] = 0
T = len(days)

C = np.zeros((nd, T), np.float32)
ti = days.get_indexer(pd.DatetimeIndex(j.date))
ok = ti >= 0
np.add.at(C, (j.di.values[ok], ti[ok]), 1)

dl = np.abs(lats[None, :] - d.lat.values[:, None]).argmin(1)
do = np.abs(lons[None, :] - d.lon.values[:, None]).argmin(1)
R = PR[dl, do, :]; TXd = TX[dl, do, :]
cs = np.cumsum(R, axis=1); cf = np.cumsum(C, axis=1)
def roll(m, n):
    o = m.copy(); o[:, n:] = m[:, n:] - m[:, :-n]; return o
dry = np.zeros_like(R); run = np.zeros(nd, np.float32)
for t in range(T):
    run = np.where(R[:, t] > 1, 0, run + 1); dry[:, t] = run
feat = {"tmax": TXd, "rain7": roll(cs, 7), "rain30": roll(cs, 30), "dry_days": dry,
        "fire7": roll(cf, 7), "fire30": roll(cf, 30)}

tt = np.arange(30, T - 1); nt = len(tt)
df = pd.DataFrame({k: M[:, tt].ravel() for k, M in feat.items()})
df["lat"] = np.repeat(d.lat.values, nt); df["lon"] = np.repeat(d.lon.values, nt)
doy = np.tile(days[tt].dayofyear.values, nd)
df["msin"] = np.sin(2 * np.pi * doy / 365.25); df["mcos"] = np.cos(2 * np.pi * doy / 365.25)
df["date"] = np.tile(days[tt].values, nd)
df["target_date"] = np.tile(days[tt + 1].values, nd)
df["y"] = (C[:, tt + 1].ravel() >= 3).astype(int)
FEATS = ["tmax", "rain7", "rain30", "dry_days", "fire7", "fire30", "lat", "lon", "msin", "mcos"]
train, test = split_by_target_date(df, "target_date", "2024-01-01")
print(f"train targets through 2023-12-31: {len(train)} (fire days {train.y.sum()}) | "
      f"test targets from 2024-01-01: {len(test)} (fire days {test.y.sum()})")

model = XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.06, subsample=0.8, colsample_bytree=0.8,
                      scale_pos_weight=min(20, (train.y == 0).sum() / max(train.y.sum(), 1)),
                      eval_metric="aucpr", n_jobs=-1)
model.fit(train[FEATS], train.y)
p = model.predict_proba(test[FEATS])[:, 1]
auc, ap = roc_auc_score(test.y, p), average_precision_score(test.y, p)
base_auc = roc_auc_score(test.y, test.fire7)
print(f"TEST 2024-2025: ROC-AUC={auc:.3f} PR-AUC={ap:.3f} base rate={test.y.mean():.3f} | persistence-only AUC={base_auc:.3f}")
print(pd.Series(model.feature_importances_, index=FEATS).sort_values(ascending=False).round(3))

(ROOT / "models").mkdir(exist_ok=True)
joblib.dump({"model": model, "features": FEATS}, ROOT / "models" / "wildfire_xgb.joblib")
json.dump({"roc_auc": auc, "pr_auc": ap, "base_rate": float(test.y.mean()), "persistence_auc": base_auc,
           "target": ">=3 detections in district next day", "test": "2024-2025"},
          open(OUT / "wildfire_metrics.json", "w"), indent=2)

t = T - 1
last = pd.DataFrame({k: M[:, t] for k, M in feat.items()})
last["lat"] = d.lat.values; last["lon"] = d.lon.values
dd = days[t].dayofyear
last["msin"] = np.sin(2 * np.pi * dd / 365.25); last["mcos"] = np.cos(2 * np.pi * dd / 365.25)
d["risk_score"] = model.predict_proba(last[FEATS])[:, 1].round(4)
d["risk_level"] = to_level(d.risk_score)
d["as_of"] = str(days[t].date())
d.to_csv(OUT / "wildfire_district.csv", index=False)
print(d.risk_level.value_counts())
print(d.sort_values("risk_score", ascending=False).head(8)[["district", "state_name", "risk_score", "risk_level"]].to_string())
