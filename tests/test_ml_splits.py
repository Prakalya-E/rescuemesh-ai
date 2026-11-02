import pandas as pd

from ml.common import split_by_target_date


def test_temporal_split_uses_label_date_at_year_boundary():
    samples = pd.DataFrame({
        "feature_date": pd.to_datetime(["2023-12-30", "2023-12-31", "2024-01-01"]),
        "target_date": pd.to_datetime(["2023-12-31", "2024-01-01", "2024-01-02"]),
        "label": [0, 1, 0],
    })

    train, test = split_by_target_date(samples, "target_date", "2024-01-01")

    assert train.feature_date.tolist() == [pd.Timestamp("2023-12-30")]
    assert test.feature_date.tolist() == [pd.Timestamp("2023-12-31"), pd.Timestamp("2024-01-01")]
    assert train.target_date.max() < pd.Timestamp("2024-01-01")
    assert test.target_date.min() >= pd.Timestamp("2024-01-01")
