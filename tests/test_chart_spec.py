"""
Tests for insights/chart_spec.py Pydantic validators.
"""

import pytest
from pydantic import ValidationError

from csv_dashboard.insights.chart_spec import ChartSpec


def _bar_spec(**overrides) -> dict:
    """Minimal valid bar chart spec, with optional field overrides."""
    base = {
        "title": "Count by Category",
        "chart_type": "bar",
        "business_question": "Which category appears most often?",
        "sql_query": "SELECT cat, COUNT(*) AS cnt FROM cleaned_data GROUP BY cat",
        "x_column": "cat",
        "y_column": "cnt",
        "aggregation": "COUNT",
        "sort_order": "desc",
        "plain_language_explanation": "Shows how often each category appears in the dataset.",
    }
    base.update(overrides)
    return base


# ── SQL table name validation ───────────────────────────────────────────────────

def test_sql_referencing_cleaned_data_is_valid():
    """Queries using FROM cleaned_data must pass validation."""
    spec = ChartSpec(**_bar_spec(
        sql_query="SELECT cat, COUNT(*) AS cnt FROM cleaned_data GROUP BY cat",
    ))
    assert spec.sql_query is not None


def test_sql_referencing_old_data_table_is_rejected():
    """Queries using FROM data (the old table name) must raise ValidationError.

    Before the fix, the validator contained:
        if 'FROM CLEANED_DATA' not in v.upper() and 'FROM DATA' not in v.upper()
    which silently accepted 'FROM data'. This test locks in the stricter behaviour.
    """
    with pytest.raises(ValidationError, match="cleaned_data"):
        ChartSpec(**_bar_spec(
            sql_query="SELECT cat, COUNT(*) AS cnt FROM data GROUP BY cat",
        ))
