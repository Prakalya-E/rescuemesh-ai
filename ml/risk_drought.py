import numpy as np, pandas as pd, joblib, json
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score, average_precision_score
from common import ROOT, OUT

df = pd.read_csv(ROOT / "data/historical/drought/events/india_historical_drought_indicator.csv")
df.columns = [c.strip() for c in df.columns]
M = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
for c in M + ["Jun-Sep", "Oct-Dec"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")
df = df.sort_values(["SUBDIVISION", "YEAR"]).reset_index(drop=True)

df["JF"] = df[["JAN", "FEB"]].sum(axis=1, min_count=2)
df["MAM"] = df[["MAR", "APR", "MAY"]].sum(axis=1, min_count=3)
df["JJ"] = df[["JUN", "JUL"]].sum(axis=1, min_count=2)

base = df[df.YEAR <= 1990].groupby("SUBDIVISION")[["Jun-Sep", "JJ", "MAM"]].mean()
base.columns = ["normal_JJAS", "normal_JJ", "normal_MAM"]
df = df.join(base, on="SUBDIVISION")

df["season_anom"] = (df["Jun-Sep"] - df.normal_JJAS) / df.normal_JJAS * 100
df["JJ_anom"] = (df.JJ - df.normal_JJ) / df.normal_JJ * 100
df["MAM_anom"] = (df.MAM - df.normal_MAM) / df.normal_MAM * 100
df["prev_season_anom"] = df.groupby("SUBDIVISION")["season_anom"].shift(1)
df["prev_octdec"] = df.groupby("SUBDIVISION")["Oct-Dec"].shift(1)
df["sub_code"] = df.SUBDIVISION.astype("category").cat.codes
df["drought"] = (df.season_anom <= -20).astype(int)

FEATS = ["JJ_anom", "MAM_anom", "JF", "prev_season_anom", "prev_octdec", "normal_JJAS", "sub_code"]
data = df.dropna(subset=["season_anom", "JJ_anom"])
train, test = data[data.YEAR <= 2000], data[data.YEAR > 2000]
print("Drought rate train/test:", train.drought.mean().round(3), test.drought.mean().round(3))

model = XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8,
                      colsample_bytree=0.8,
                      scale_pos_weight=(1 - train.drought.mean()) / max(train.drought.mean(), 1e-6),
                      eval_metric="logloss")
model.fit(train[FEATS], train.drought)
p = model.predict_proba(test[FEATS])[:, 1]
auc, ap = roc_auc_score(test.drought, p), average_precision_score(test.drought, p)
print(f"TEST (years 2001-2015) ROC-AUC={auc:.3f}  PR-AUC={ap:.3f}  base rate={test.drought.mean():.3f}")

(ROOT / "models").mkdir(exist_ok=True)
joblib.dump({"model": model, "features": FEATS,
             "subdivisions": list(df.SUBDIVISION.astype("category").cat.categories)},
            ROOT / "models" / "drought_xgb.joblib")
json.dump({"roc_auc": auc, "pr_auc": ap, "test_years": "2001-2015",
           "target": "Jun-Sep rainfall deficit >= 20% of 1901-1990 normal",
           "issued": "end of July"}, open(OUT / "drought_metrics.json", "w"), indent=2)
imp = pd.Series(model.feature_importances_, index=FEATS).sort_values(ascending=False)
print(imp.round(3))
