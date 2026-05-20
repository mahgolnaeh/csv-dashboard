"""
Tests for charts/renderer.py.
One test per chart_type: bar, line, scatter, histogram, heatmap.
No LLM mocking needed -- renderer is pure Plotly, no network calls.
"""

import pandas as pd
import plotly.graph_objects as go

from csv_dashboard.charts.renderer import render
from csv_dashboard.insights.chart_spec import ChartSpec


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _spec(**kwargs) -> ChartSpec:
    """Build a bar ChartSpec with sensible defaults, overriding with kwargs."""
    defaults = {
        "title": "Test Chart",
        "chart_type": "bar",
        "business_question": "What is the count per category?",
        "sql_query": "SELECT cat, COUNT(*) AS cnt FROM cleaned_data GROUP BY cat",
        "x_column": "cat",
        "y_column": "cnt",
        "aggregation": "COUNT",
        "sort_order": "desc",
        "plain_language_explanation": "Shows the count of each category in the dataset.",
    }
    defaults.update(kwargs)
    return ChartSpec(**defaults)


# ── Tests ───────────────────────────────────────────────────────────────────────

def test_render_bar_returns_figure():
    spec = _spec(
        chart_type="bar",
        x_column="sex",
        y_column="cnt",
        sql_query="SELECT sex, COUNT(*) AS cnt FROM cleaned_data GROUP BY sex",
        aggregation="COUNT",
        sort_order="desc",
        x_label="Gender",
        y_label="Count",
    )
    df = pd.DataFrame({"sex": ["female", "male"], "cnt": [233, 109]})

    fig = render(spec, df)

    assert isinstance(fig, go.Figure)


def test_render_line_returns_figure():
    spec = _spec(
        chart_type="line",
        x_column="month",
        y_column="avg_price",
        sql_query=(
            "SELECT month, AVG(price) AS avg_price FROM cleaned_data "
            "GROUP BY month ORDER BY month"
        ),
        aggregation="AVG",
        sort_order="none",
        x_label="Month",
        y_label="Average Price",
    )
    df = pd.DataFrame({
        "month": ["2020-01", "2020-02", "2020-03", "2020-04"],
        "avg_price": [100.0, 120.0, 110.0, 135.0],
    })

    fig = render(spec, df)

    assert isinstance(fig, go.Figure)


def test_render_scatter_returns_figure():
    spec = _spec(
        chart_type="scatter",
        x_column="age",
        y_column="fare",
        sql_query="SELECT age, fare FROM cleaned_data",
        aggregation="NONE",
        sort_order="none",
        x_label="Age",
        y_label="Fare (USD)",
    )
    df = pd.DataFrame({
        "age": [22.0, 35.0, 45.0, 18.0, 29.0, 54.0, 31.0],
        "fare": [7.25, 53.1, 71.3, 12.0, 8.5, 263.0, 26.0],
    })

    fig = render(spec, df)

    assert isinstance(fig, go.Figure)


def test_render_histogram_returns_figure():
    spec = _spec(
        chart_type="histogram",
        x_column="age",
        y_column=None,
        sql_query="SELECT age FROM cleaned_data WHERE age IS NOT NULL",
        aggregation="NONE",
        sort_order="none",
        x_label="Age",
        y_label=None,
    )
    df = pd.DataFrame({
        "age": [22.0, 35.0, 45.0, 18.0, 29.0, 60.0, 42.0, 38.0, 55.0],
    })

    fig = render(spec, df)

    assert isinstance(fig, go.Figure)


def test_render_heatmap_returns_figure():
    spec = _spec(
        chart_type="heatmap",
        x_column=None,
        y_column=None,
        sql_query="SELECT age, fare, survived FROM cleaned_data",
        aggregation="COUNT",
        sort_order="none",
        plain_language_explanation="Shows which numeric columns move together in the dataset.",
    )
    df = pd.DataFrame({
        "age": [22.0, 35.0, 45.0, 18.0, 29.0],
        "fare": [7.25, 53.1, 71.3, 12.0, 8.5],
        "survived": [1.0, 0.0, 1.0, 0.0, 1.0],
    })

    fig = render(spec, df)

    assert isinstance(fig, go.Figure)
