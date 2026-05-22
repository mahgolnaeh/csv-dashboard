"""
Tests for charts/engine.py (deterministic fallback chart engine).

Regression coverage: a boolean column must be treated as CATEGORICAL
(a 2-value count bar chart), not numeric. Pandas considers `bool` a
numeric dtype, so the engine previously fed booleans to .quantile()
in _has_outliers, crashing with:
    TypeError: numpy boolean subtract, the `-` operator, is not supported
"""

import pandas as pd

from csv_dashboard.charts import engine


def _bool_df() -> pd.DataFrame:
    return pd.DataFrame({
        "city": [["Berlin", "Munich", "Hamburg", "Cologne"][i % 4] for i in range(40)],
        "is_active": [bool(i % 3) for i in range(40)],
        "revenue": [100 + i * 7 for i in range(40)],
    })


def test_boolean_column_does_not_crash_engine() -> None:
    charts = engine.generate_charts(_bool_df(), "bools.csv")  # must not raise
    assert len(charts) >= 1


def test_boolean_column_charted_as_categorical_not_numeric() -> None:
    charts = engine.generate_charts(_bool_df(), "bools.csv", max_charts=None)
    titles = [c["title"] for c in charts]
    rules = {c["title"]: c["rule"] for c in charts}

    # Boolean gets a count bar chart (R03), like a 2-value categorical.
    assert "Count of 'is_active'" in titles
    assert rules["Count of 'is_active'"] == "R03"

    # Boolean must NOT be treated as numeric (no histogram / distribution).
    assert "Distribution: is_active" not in titles


def test_has_outliers_returns_false_for_bool() -> None:
    assert engine._has_outliers(pd.Series([True, False, True, False, True])) is False
