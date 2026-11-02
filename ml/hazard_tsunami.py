import glob, numpy as np, pandas as pd, geopandas as gpd
from common import *

d = load_districts()
g = gpd.read_file(ROOT / "data/geospatial/administrative/districts/district_nwic.GeoJSON").to_crs(7755)
shp = glob.glob(str(ROOT / "data/geospatial/coastline/**/ne_10m_coastline.shp"), recursive=True)[0]
coast = gpd.read_file(shp).cx[60:100, 5:40].to_crs(7755)
cu = coast.geometry.union_all()
d["coast_km"] = (g.geometry.distance(cu) / 1000).round(1).values

ev = pd.read_csv(ROOT / "data/historical/tsunami/events/noaa_tsunami_india_events.csv")
ev = ev.dropna(subset=["latitude", "longitude"])
w = 1 + pd.to_numeric(ev.maxWaterHeight, errors="coerce").fillna(0).values / 5
dist = haversine_km(d.lat.values[:, None], d.lon.values[:, None], ev.latitude.values[None, :], ev.longitude.values[None, :])
d["historic_exposure"] = ((dist <= 1000) * w[None, :]).sum(1)

prox = np.clip(1 - d.coast_km / 30, 0, 1)
score = prox * (0.4 + 0.6 * norm(d.historic_exposure))
d["risk_score"] = score.round(3).values
d["risk_level"] = to_level(score)
d.to_csv(OUT / "tsunami_district.csv", index=False)
print(d.risk_level.value_counts())
print(d.sort_values("risk_score", ascending=False).head(10)[["district", "state_name", "coast_km", "historic_exposure", "risk_level"]].to_string())
