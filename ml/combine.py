import pandas as pd
from common import OUT

parts = []
for h in ["flood", "cyclone", "earthquake", "landslide", "wildfire", "tsunami"]:
    p = OUT / f"{h}_district.csv"
    if not p.exists():
        print("missing:", h); continue
    x = pd.read_csv(p)
    x["hazard"] = h
    parts.append(x[["district", "state_name", "lat", "lon", "hazard", "risk_score", "risk_level"]])
long = pd.concat(parts, ignore_index=True)
long.to_csv(OUT / "all_hazards_long.csv", index=False)
rank = {"low": 0, "medium": 1, "high": 2, "severe": 3}
long["r"] = long.risk_level.map(rank)
top = long.sort_values(["district", "state_name", "r", "risk_score"], ascending=[True, True, False, False]) \
          .drop_duplicates(["district", "state_name"])
top[["district", "state_name", "hazard", "risk_level"]].rename(columns={"hazard": "top_hazard"}).to_csv(OUT / "district_top_hazard.csv", index=False)
print(long.groupby(["hazard", "risk_level"]).size().unstack(fill_value=0))
