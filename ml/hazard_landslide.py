import numpy as np, pandas as pd
from common import *

d = load_districts()
l = pd.read_csv(ROOT / "data/historical/landslide/events/nasa_india_landslide_catalog.csv",
                usecols=["latitude", "longitude", "landslide_trigger", "fatality_count"])
l = l.dropna(subset=["latitude", "longitude"])
l["fatality_count"] = pd.to_numeric(l.fatality_count, errors="coerce").fillna(0)
l["rain"] = l.landslide_trigger.astype(str).str.contains("rain|downpour|monsoon|cyclone", case=False)
dist = haversine_km(d.lat.values[:, None], d.lon.values[:, None], l.latitude.values[None, :], l.longitude.values[None, :])
near = dist <= 50
d["events_2007_2016"] = near.sum(1)
d["fatalities"] = (near * l.fatality_count.values[None, :]).sum(1)
d["rain_triggered"] = (near & l.rain.values[None, :]).sum(1)
score = 0.5 * norm(d.events_2007_2016) + 0.3 * norm(d.fatalities) + 0.2 * norm(d.rain_triggered)
d["risk_score"] = score.round(3).values
d["risk_level"] = to_level(score)
d.to_csv(OUT / "landslide_district.csv", index=False)
print(d.risk_level.value_counts())
print(d.sort_values("risk_score", ascending=False).head(10)[["district", "state_name", "events_2007_2016", "fatalities", "risk_level"]].to_string())
