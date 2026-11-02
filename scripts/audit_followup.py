"""Read-only follow-up checks."""
import pandas as pd
from pathlib import Path
R = Path(__file__).resolve().parent.parent / "data" / "historical"
def h(t): print(f"\n=== {t}")

h("Earthquake files")
a = pd.read_csv(R/"earthquake/events/usgs_earthquakes_india_2000_2024.csv")
b = pd.read_csv(R/"earthquake/events/usgs_earthquakes_india_region_2000_2024.csv")
print("small-file ids also in region file:", round(a["id"].isin(b["id"]).mean(), 3))
print("event types (region):", b["type"].value_counts().to_dict())
print("mag summary (region):", b["mag"].describe().round(2).to_dict())
print("M>=4.5:", int((b["mag"] >= 4.5).sum()), " M>=5.5:", int((b["mag"] >= 5.5).sum()))

h("Wildfire")
w = pd.read_csv(R/"wildfire/events/wildfire_detections_clean.csv",
                usecols=["Date", "Year", "OriginalYear", "Sensor", "State"])
d = pd.to_datetime(w["Date"], errors="coerce")
print("rows:", len(w), "| date range:", d.min(), "->", d.max(), "| unparseable:", round(d.isna().mean(), 4))
print("Year != OriginalYear:", round((w["Year"] != w["OriginalYear"]).mean(), 4))
print("Date.year != Year:", round((d.dt.year != w["Year"]).mean(), 4))
print("rows per calendar year:", d.dt.year.value_counts().sort_index().to_dict())
print("sensors:", w["Sensor"].value_counts().to_dict())

h("Flood inventory")
f = pd.read_csv(R/"flood/events/India_Flood_Inventory_v3.csv")
print("raw Start Date samples:", f["Start Date"].head(3).tolist())
sd = pd.to_datetime(f["Start Date"], errors="coerce", dayfirst=True)
print("unparseable:", round(sd.isna().mean(), 4), "| range:", sd.min(), "->", sd.max())
print("events per year (last 12):", sd.dt.year.value_counts().sort_index().tail(12).to_dict())
print("Districts null:", round(f["Districts"].isna().mean(), 3), "| State null:", round(f["State"].isna().mean(), 3))
print("dup UEI:", int(f["UEI"].duplicated().sum()))
print("Main Cause:", f["Main Cause"].value_counts().head(8).to_dict())
print("Event Source:", f["Event Source"].value_counts().head(6).to_dict())

h("Weather (NASA POWER precipitation)")
p = R/"weather/nasa_PRECTOTCORR_20201201_20250630.csv"
lo, hi, cells = 10**9, 0, set()
for c in pd.read_csv(p, usecols=["LAT", "LON", "YEAR", "DOY"], chunksize=500000):
    k = c["YEAR"] * 1000 + c["DOY"]
    lo, hi = min(lo, int(k.min())), max(hi, int(k.max()))
    cells.update(zip(c["LAT"], c["LON"]))
print("first (YEAR*1000+DOY):", lo, "| last:", hi, "| grid cells:", len(cells))

h("Cyclone")
ti = pd.read_csv(R/"cyclone/events/ibtracs_india_tracks.csv", usecols=["SID", "SEASON"])
tn = pd.read_csv(R/"cyclone/events/ibtracs_north_indian_ocean.csv", usecols=["SID", "SEASON"])
print("storms india file:", ti["SID"].nunique(), "| NIO file:", tn["SID"].nunique())
print("india SIDs found in NIO file:", round(ti["SID"].drop_duplicates().isin(tn["SID"]).mean(), 3))
print("india seasons:", ti["SEASON"].min(), "->", ti["SEASON"].max(),
      "| storms since 1990:", ti[ti["SEASON"] >= 1990]["SID"].nunique())

h("Drought labels")
dr = pd.read_csv(R/"drought/events/india_historical_drought_indicator.csv")
print(dr["drought_class"].value_counts(dropna=False).to_dict())
