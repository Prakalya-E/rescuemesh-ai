import numpy as np, pandas as pd
from common import *

d = load_districts()
t = pd.read_csv(ROOT / "data/historical/cyclone/events/ibtracs_india_tracks.csv",
                usecols=["SID", "SEASON", "LAT", "LON", "WMO_WIND", "USA_WIND"], low_memory=False)
for c in ["SEASON", "LAT", "LON", "WMO_WIND", "USA_WIND"]:
    t[c] = pd.to_numeric(t[c], errors="coerce")
t["wind"] = t.WMO_WIND.fillna(t.USA_WIND)
t = t.dropna(subset=["LAT", "LON", "SEASON"])
t = t[t.SEASON >= 1990]
years = t.SEASON.max() - 1990 + 1
rows = []
for _, r in d.iterrows():
    sub = t[haversine_km(r.lat, r.lon, t.LAT.values, t.LON.values) <= 150]
    rows.append({
        "storms_per_year": sub.SID.nunique() / years,
        "severe_storms": sub[sub.wind >= 48].SID.nunique(),
        "very_severe_storms": sub[sub.wind >= 64].SID.nunique(),
        "max_wind_kt": sub.wind.max() if len(sub) else 0,
    })
d = pd.concat([d, pd.DataFrame(rows).fillna(0)], axis=1)
score = 0.4 * norm(d.storms_per_year) + 0.3 * norm(d.severe_storms) + 0.2 * norm(d.very_severe_storms) + 0.1 * norm(d.max_wind_kt)
d["risk_score"] = score.round(3).values
d["risk_level"] = to_level(score)
d.to_csv(OUT / "cyclone_district.csv", index=False)
print(d.risk_level.value_counts())
print(d.sort_values("risk_score", ascending=False).head(10).to_string())
