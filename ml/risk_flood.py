import re, json, numpy as np, pandas as pd, joblib
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score, average_precision_score
from common import ROOT, OUT, load_districts, to_level

def nrm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())

d = load_districts()
nd = len(d)
by_ds, by_d = {}, {}
for i, (dn, sn) in enumerate(zip(d.district, d.state_name)):
    by_ds[(nrm(sn), nrm(dn))] = i
    by_d.setdefault(nrm(dn), []).append(i)

def match(state, dist):
    k = (nrm(state), nrm(dist))
    if k in by_ds:
        return by_ds[k]
    c = by_d.get(nrm(dist), [])
    return c[0] if len(c) == 1 else None

# daily rainfall grid
w = pd.read_csv(ROOT / "data/historical/weather/nasa_PRECTOTCORR_20201201_20250630.csv")
w["date"] = pd.to_datetime(w.YEAR.astype(str) + "-01-01") + pd.to_timedelta(w.DOY - 1, unit="D")
lats = np.sort(w.LAT.unique()); lons = np.sort(w.LON.unique())
days = pd.DatetimeIndex(np.sort(w.date.unique()))
grid = np.zeros((len(lats), len(lons), len(days)), np.float32)
v = w.PRECTOTCORR.values.astype(np.float32); v[v < 0] = 0
grid[np.searchsorted(lats, w.LAT.values), np.searchsorted(lons, w.LON.values), days.get_indexer(w.date)] = v
del w
T = len(days)
print("weather days:", days[0].date(), "to", days[-1].date())

# district series from nearest grid cell to centroid
dl = np.abs(lats[None, :] - d.lat.values[:, None]).argmin(1)
do = np.abs(lons[None, :] - d.lon.values[:, None]).argmin(1)
R = grid[dl, do, :]
cs = np.cumsum(R, axis=1)
def roll(n):
    out = cs.copy(); out[:, n:] = cs[:, n:] - cs[:, :-n]; return out
feat = {"rain1": R, "rain3": roll(3), "rain7": roll(7), "rain14": roll(14), "rain30": roll(30)}

# flood events matched to districts by name
inv = pd.read_csv(ROOT / "data/historical/flood/events/India_Flood_Inventory_v3.csv", low_memory=False)
inv["date"] = pd.to_datetime(inv["Start Date"], dayfirst=True, errors="coerce").dt.normalize()
inv = inv.dropna(subset=["date"])
inv["dname"] = inv["Districts"].fillna(inv["Location"]).astype(str).str.split(r"\s*[,;]\s*|\s+and\s+", regex=True)
ev = inv[["date", "State", "dname"]].explode("dname")
ev["dname"] = ev.dname.astype(str).str.strip()
ev = ev[ev.dname.str.len() > 1].copy()
ev["di"] = [match(s, n) for s, n in zip(ev.State, ev.dname)]
print(f"event-district rows: {len(ev)} | matched: {ev.di.notna().mean():.1%}")
print("most common unmatched names:\n", ev[ev.di.isna()].dname.value_counts().head(8).to_string())
ev = ev.dropna(subset=["di"]).copy()
ev["di"] = ev.di.astype(int)
hist = np.bincount(ev[ev.date < "2021-01-01"].di, minlength=nd).astype(float)

Y = np.zeros((nd, T), bool); X = np.zeros((nd, T), bool)
ev["ti"] = days.get_indexer(ev.date)
for i, t in zip(ev.di, ev.ti):
    if t >= 0:
        Y[i, t] = True
        X[i, t + 1:t + 8] = True

tt = np.where((days >= "2021-01-01") & (days <= "2023-12-31"))[0]
nt = len(tt)
df = pd.DataFrame({k: M[:, tt].ravel() for k, M in feat.items()})
df["hist"] = np.repeat(hist, nt)
df["lat"] = np.repeat(d.lat.values, nt)
df["lon"] = np.repeat(d.lon.values, nt)
doy = np.tile(days[tt].dayofyear.values, nd)
df["msin"] = np.sin(2 * np.pi * doy / 365.25)
df["mcos"] = np.cos(2 * np.pi * doy / 365.25)
df["year"] = np.tile(days[tt].year.values, nd)
df["y"] = Y[:, tt].ravel()
df = df[~(X[:, tt].ravel() & ~df.y.values)]
FEATS = ["rain1", "rain3", "rain7", "rain14", "rain30", "hist", "lat", "lon", "msin", "mcos"]
train, test = df[df.year <= 2022], df[df.year == 2023]
print(f"train rows {len(train)} (floods {train.y.sum()}) | test rows {len(test)} (floods {test.y.sum()})")

neg, pos = (train.y == 0).sum(), max(train.y.sum(), 1)
model = XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.05, subsample=0.8,
                      colsample_bytree=0.8, scale_pos_weight=min(50, neg / pos),
                      eval_metric="aucpr", n_jobs=-1)
model.fit(train[FEATS], train.y)
p = model.predict_proba(test[FEATS])[:, 1]
auc, ap = roc_auc_score(test.y, p), average_precision_score(test.y, p)
thr = np.quantile(p, 0.95)
recall5 = float((p[test.y.values == 1] >= thr).mean())
print(f"TEST 2023: ROC-AUC={auc:.3f} PR-AUC={ap:.4f} base rate={test.y.mean():.4f} recall in top-5% risk days={recall5:.2f}")
print(pd.Series(model.feature_importances_, index=FEATS).sort_values(ascending=False).round(3))

(ROOT / "models").mkdir(exist_ok=True)
joblib.dump({"model": model, "features": FEATS}, ROOT / "models" / "flood_xgb.joblib")
json.dump({"roc_auc": auc, "pr_auc": ap, "base_rate": float(test.y.mean()), "recall_top5pct": recall5,
           "test": "2023, trained on 2021-2022"}, open(OUT / "flood_metrics.json", "w"), indent=2)

# score every district using the latest weather day
t = T - 1
last = pd.DataFrame({k: M[:, t] for k, M in feat.items()})
last["hist"] = hist; last["lat"] = d.lat.values; last["lon"] = d.lon.values
dd = days[t].dayofyear
last["msin"] = np.sin(2 * np.pi * dd / 365.25); last["mcos"] = np.cos(2 * np.pi * dd / 365.25)
d["risk_score"] = model.predict_proba(last[FEATS])[:, 1].round(4)
d["risk_level"] = to_level(d.risk_score)
d["as_of"] = str(days[t].date())
d.to_csv(OUT / "flood_district.csv", index=False)
print(d.risk_level.value_counts())
print(d.sort_values("risk_score", ascending=False).head(8)[["district", "state_name", "risk_score", "risk_level"]].to_string())
