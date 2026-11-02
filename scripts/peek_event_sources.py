
import pandas as pd
from pathlib import Path

H = Path("data/historical")


def peek(title, path, cols, n=2):
    df = pd.read_csv(path, dtype=str, nrows=3000, low_memory=False)

    print(
        f"\n== {title}: {path.name} | columns I expected but did not find: "
        f"{[c for c in cols if c not in df.columns]}"
    )

    print(
        df[[c for c in cols if c in df.columns]]
        .head(n)
        .to_string(max_colwidth=40)
    )


peek(
    "earthquake",
    H / "earthquake/events/usgs_earthquakes_india_region_2000_2024.csv",
    ["id", "time", "latitude", "longitude", "mag", "magType", "depth", "place"]
)

peek(
    "landslide",
    H / "landslide/events/nasa_india_landslide_catalog.csv",
    [
        "event_id", "event_date", "event_title", "landslide_category",
        "landslide_trigger", "landslide_size", "fatality_count",
        "injury_count", "admin_division_name", "latitude", "longitude"
    ]
)

peek(
    "flood",
    H / "flood/events/India_Flood_Inventory_v3.csv",
    [
        "UEI", "Start Date", "End Date", "Main Cause", "Districts",
        "State", "Human fatality", "Human injured", "Human Displaced"
    ]
)

peek(
    "tsunami",
    H / "tsunami/events/noaa_tsunami_india_events.csv",
    [
        "id", "year", "month", "day", "locationName", "latitude",
        "longitude", "eqMagnitude", "maxWaterHeight", "deaths", "causeCode"
    ]
)

c = pd.read_csv(
    H / "cyclone/events/ibtracs_india_tracks.csv",
    dtype=str,
    low_memory=False,
    usecols=[
        "SID", "SEASON", "NAME", "ISO_TIME", "LAT", "LON",
        "WMO_WIND", "WMO_PRES", "USA_WIND", "USA_PRES",
        "USA_SSHS", "BASIN", "NATURE"
    ]
)

print("\n== cyclone: first 2 rows")
print(c.head(2).to_string())

print("\n== cyclone: 2 rows from the middle")
print(c.iloc[30000:30002].to_string())

blank = lambda s: (s.isna() | s.str.strip().isin(["", "nan"])).mean()

print(
    "distinct storms:", c.SID.nunique(),
    "| blank share WMO_WIND:", round(blank(c.WMO_WIND), 2),
    "| USA_WIND:", round(blank(c.USA_WIND), 2)
)
