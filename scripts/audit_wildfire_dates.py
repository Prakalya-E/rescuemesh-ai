"""Read-only: which wildfire detections had their dates moved, and what do the original dates look like?"""
import pandas as pd
w = pd.read_csv(r"data\historical\wildfire\events\wildfire_detections_clean.csv", usecols=["Date", "Year", "OriginalYear"])
w["Date"] = pd.to_datetime(w["Date"])
mm = w[w.Year != w.OriginalYear]
orig = pd.to_datetime(dict(year=mm.OriginalYear, month=mm.Date.dt.month, day=mm.Date.dt.day), errors="coerce")
print("rows whose year was changed:", len(mm), "| rebuilt original dates that are invalid:", int(orig.isna().sum()))
print("\nSHIFTED rows: count by (year now shown) x (month):")
print(mm.assign(m=mm.Date.dt.month).groupby(["Year", "m"]).size().unstack(fill_value=0).to_string())
ok = w[w.Year == w.OriginalYear]
print("\nUNSHIFTED rows: count by (year) x (month):")
print(ok.assign(y=ok.Date.dt.year, m=ok.Date.dt.month).groupby(["y", "m"]).size().unstack(fill_value=0).to_string())
