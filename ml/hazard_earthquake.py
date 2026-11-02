import numpy as np, pandas as pd
from common import *

d = load_districts()
eq = pd.read_csv(ROOT / "data/historical/earthquake/events/usgs_earthquakes_india_region_2000_2024.csv",
                 usecols=["latitude", "longitude", "mag"]).dropna()
eq = eq[eq.mag >= 3.5]
YEARS = 25
dist = haversine_km(d.lat.values[:, None], d.lon.values[:, None],
                    eq.latitude.values[None, :], eq.longitude.values[None, :])
near = dist <= 100
mag = eq.mag.values[None, :]
d["m45_per_year"] = (near & (mag >= 4.5)).sum(1) / YEARS
d["m55_count"] = (near & (mag >= 5.5)).sum(1)
d["max_mag"] = np.where(near, mag, 0).max(1)
score = 0.5 * norm(d.m45_per_year) + 0.3 * norm(d.max_mag) + 0.2 * norm(d.m55_count)
d["risk_score"] = score.round(3).values
d["risk_level"] = to_level(score)
d.to_csv(OUT / "earthquake_district.csv", index=False)
print(d.risk_level.value_counts())
print(d.sort_values("risk_score", ascending=False).head(10).to_string())
