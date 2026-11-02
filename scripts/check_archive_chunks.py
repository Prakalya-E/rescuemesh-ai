import pandas as pd
from pathlib import Path
d = Path(r"data\historical\wildfire\firms_archive")
files = sorted(d.rglob("*.csv")) if d.exists() else []
print("csv chunks found:", len(files))
for f in files:
    df = pd.read_csv(f)
    dates = pd.to_datetime(df["acq_date"], errors="coerce") if "acq_date" in df else pd.Series(dtype="datetime64[ns]")
    ok = dates.dropna()
    span = f"{ok.min().date()} -> {ok.max().date()}" if len(ok) else "no valid dates"
    print(f"{f.relative_to(d)} | rows={len(df)} | dates {span} | unreadable dates={int(dates.isna().sum())}")
    if "satellite" in df:
        print("   satellites:", df["satellite"].value_counts().to_dict(), "| columns:", list(df.columns)[:8])
