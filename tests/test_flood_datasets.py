from collections import Counter

import numpy as np
import pandas as pd

from scripts.build_flood_rainfall_features import (
    deduplicate_event_district_rows,
    explode_inventory,
    normalize,
    summarize_rainfall_window,
)


def test_inventory_expansion_explains_flood_event_district_duplicates():
    expanded = explode_inventory()
    distinct = deduplicate_event_district_rows(expanded)
    key_columns = ["UEI", "Start Date", "State Source", "District Source"]
    feature = pd.read_csv("data/historical/flood/events/flood_2018_rainfall_features_TEST.csv")
    expected_keys = Counter(
        (str(r.UEI), str(r["Start Date"]), normalize(r["State Source"]), normalize(r["District Source"]))
        for _, r in feature.iterrows()
    )
    actual_keys = Counter(
        (str(r.UEI), str(r["Start Date"]), normalize(r["State Source"]), normalize(r["District Source"]))
        for _, r in expanded.iterrows()
    )

    assert len(expanded) == 565
    assert len(distinct) == 562
    assert sum(v - 1 for v in actual_keys.values() if v > 1) == 3
    assert actual_keys == expected_keys
    assert set(key_columns) <= set(expanded.columns)


def test_flood_feature_variants_have_expected_schema_and_usable_subset():
    source = pd.read_csv("data/historical/flood/events/flood_2018_rainfall_features.csv")
    test = pd.read_csv("data/historical/flood/events/flood_2018_rainfall_features_TEST.csv")
    usable = pd.read_csv("data/processed/flood/flood_rainfall_features_usable.csv")
    key = ["UEI", "Start Date", "State Source", "District Source"]

    assert list(source.columns) == list(test.columns) == list(usable.columns)
    assert len(source) == len(test) == 565
    assert len(usable) == 546
    assert source.duplicated().sum() == test.duplicated().sum() == usable.duplicated().sum() == 3
    required = ["Start Day Mean Rainfall (mm)", "Previous 3 Days Mean Daily Rainfall (mm)"]
    complete_test = test.dropna(subset=required)
    assert Counter(map(tuple, usable[key].astype(str).to_numpy())) == Counter(
        map(tuple, complete_test[key].astype(str).to_numpy())
    )


def test_previous_three_day_rainfall_excludes_event_day_and_future():
    rain = np.array([[[1.0]], [[2.0]], [[3.0]], [[4.0]], [[500.0]]])
    mask = np.array([[True]])

    count, event_day, event_cov, previous, previous_cov, status = summarize_rainfall_window(
        rain, mask, time_index=3
    )

    assert count == 1
    assert event_day == 4.0
    assert event_cov == 100.0
    assert previous == 2.0
    assert previous_cov == 100.0
    assert status == "Start-day rainfall available"
