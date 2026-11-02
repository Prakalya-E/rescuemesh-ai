import pandas as pd
w = pd.read_csv(r"data\historical\wildfire\events\wildfire_detections_clean.csv", usecols=["Date","Year","OriginalYear"])
print(w.OriginalYear.value_counts().sort_index().to_string())
mm = w[w.Year != w.OriginalYear]
print("\nmismatched rows:", len(mm))
print(mm.groupby(["OriginalYear","Year"]).size().to_string())
print(mm.head(5).to_string())
