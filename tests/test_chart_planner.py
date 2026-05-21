"""
Tests for agents/chart_planner.py.
All LLM calls are mocked -- no network, no API key needed.
"""

import json

from csv_dashboard.agents.chart_planner import plan_charts
from csv_dashboard.insights.chart_spec import ChartSpec
from csv_dashboard.insights.llm_client import LLMError

# ── Fixtures ────────────────────────────────────────────────────────────────────

VALID_JSON_RESPONSE = json.dumps({
    "charts": [
        {
            "title": "Survival by Gender",
            "chart_type": "bar",
            "business_question": "How does survival rate differ by gender?",
            "sql_query": (
                "SELECT sex, COUNT(*) AS cnt FROM cleaned_data "
                "GROUP BY sex ORDER BY cnt DESC"
            ),
            "x_column": "sex",
            "y_column": "cnt",
            "color_column": None,
            "aggregation": "COUNT",
            "sort_order": "desc",
            "limit": 10,
            "x_label": "Gender",
            "y_label": "Count",
            "plain_language_explanation": (
                "Shows the number of passengers by gender to compare survival rates."
            ),
        },
        {
            "title": "Age Distribution of Passengers",
            "chart_type": "histogram",
            "business_question": "What is the age distribution of passengers?",
            "sql_query": "SELECT age FROM cleaned_data WHERE age IS NOT NULL",
            "x_column": "age",
            "y_column": None,
            "color_column": None,
            "aggregation": "NONE",
            "sort_order": "none",
            "limit": None,
            "x_label": "Age",
            "y_label": None,
            "plain_language_explanation": (
                "Shows how passenger ages are spread across the full dataset."
            ),
        },
        {
            "title": "Survival Rate by Passenger Class",
            "chart_type": "bar",
            "business_question": "Which passenger class had the highest survival rate?",
            "sql_query": (
                "SELECT pclass, AVG(survived) AS survival_rate FROM cleaned_data "
                "GROUP BY pclass ORDER BY pclass"
            ),
            "x_column": "pclass",
            "y_column": "survival_rate",
            "color_column": None,
            "aggregation": "AVG",
            "sort_order": "none",
            "limit": 10,
            "x_label": "Passenger Class",
            "y_label": "Survival Rate",
            "plain_language_explanation": (
                "Compares survival rates across first, second, and third class passengers."
            ),
        },
    ]
})

MINIMAL_PROFILE = {
    "filename": "titanic.csv",
    "row_count": 891,
    "column_count": 5,
    "duplicate_row_count": 0,
    "semantic_type_summary": {
        "numeric": 3,
        "categorical": 1,
        "datetime": 0,
        "boolean": 1,
        "identifier": 0,
        "text": 0,
    },
    "columns": {
        "sex": {
            "semantic_type": "categorical",
            "missing_pct": 0.0,
            "unique_count": 2,
        },
        "age": {
            "semantic_type": "numeric",
            "missing_pct": 0.2,
            "unique_count": 89,
            "numeric_summary": {
                "min": 0.42, "max": 80.0, "mean": 29.7, "median": 28.0,
                "std": 14.5, "skewness": 0.4, "outlier_count_iqr": 11,
            },
        },
        "pclass": {
            "semantic_type": "numeric",
            "missing_pct": 0.0,
            "unique_count": 3,
        },
        "survived": {
            "semantic_type": "boolean",
            "missing_pct": 0.0,
            "unique_count": 2,
        },
        "fare": {
            "semantic_type": "numeric",
            "missing_pct": 0.0,
            "unique_count": 248,
            "numeric_summary": {
                "min": 0.0, "max": 512.0, "mean": 32.2, "median": 14.4,
                "std": 49.7, "skewness": 4.8, "outlier_count_iqr": 116,
            },
        },
    },
    "warnings": [],
}

QUALITY_CONTEXT = "No major quality issues detected."


# ── Tests ───────────────────────────────────────────────────────────────────────

def test_plan_charts_returns_chart_specs_on_valid_llm_response(mocker):
    """Valid JSON from LLM produces a list of ChartSpec objects."""
    mocker.patch(
        "csv_dashboard.agents.chart_planner.call_llm",
        return_value=VALID_JSON_RESPONSE,
    )

    result = plan_charts(MINIMAL_PROFILE, QUALITY_CONTEXT)

    assert len(result) == 3
    assert all(isinstance(spec, ChartSpec) for spec in result)
    assert result[0].title == "Survival by Gender"
    assert result[1].chart_type == "histogram"


def test_plan_charts_returns_empty_on_malformed_json(mocker):
    """Malformed JSON on every attempt returns empty list without raising."""
    mocker.patch(
        "csv_dashboard.agents.chart_planner.call_llm",
        return_value="this is not valid json { broken",
    )

    result = plan_charts(MINIMAL_PROFILE, QUALITY_CONTEXT)

    assert result == []


def test_plan_charts_returns_empty_on_llm_error(mocker):
    """LLMError on every attempt returns empty list without raising."""
    mocker.patch(
        "csv_dashboard.agents.chart_planner.call_llm",
        side_effect=LLMError("OpenRouter unreachable"),
    )

    result = plan_charts(MINIMAL_PROFILE, QUALITY_CONTEXT)

    assert result == []
