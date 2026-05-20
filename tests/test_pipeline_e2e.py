"""
End-to-end tests for orchestrator/pipeline.py.

Both LLM agents (plan_charts, write_insights) are mocked.
All other stages run as real code: DuckDB loads the CSV, data_quality
creates the cleaned_data VIEW, profiler runs, renderer renders Plotly figures.

The SQL queries in LLM_SPECS must reference real column names from the
synthetic CSV (sex, age, fare) so that the executor can run them against
the actual DuckDB connection.
"""

from pathlib import Path

import pytest

from csv_dashboard.insights.chart_spec import ChartSpec
from csv_dashboard.orchestrator.pipeline import PipelineResult, run


# ── Synthetic CSV ────────────────────────────────────────────────────────────────

SYNTHETIC_CSV = """\
sex,age,fare
female,29,211.34
male,1,151.55
female,2,151.55
male,30,151.55
female,25,151.55
male,48,52.00
male,63,90.00
female,39,52.00
male,71,49.50
male,22,7.25
female,26,78.85
male,30,13.00
female,16,86.50
male,45,512.33
female,22,61.98
male,34,6.50
female,19,30.00
male,22,7.23
female,22,7.23
male,28,22.53
"""

# ── ChartSpec fixtures (SQL validated against the synthetic cleaned_data) ────────

LLM_SPECS = [
    ChartSpec(
        title="Passenger Count by Gender",
        chart_type="bar",
        business_question="How many male vs female passengers were there?",
        sql_query=(
            "SELECT sex, COUNT(*) AS cnt FROM cleaned_data "
            "GROUP BY sex ORDER BY cnt DESC"
        ),
        x_column="sex",
        y_column="cnt",
        aggregation="COUNT",
        sort_order="desc",
        limit=10,
        x_label="Gender",
        y_label="Count",
        plain_language_explanation="Shows the number of passengers by gender.",
    ),
    ChartSpec(
        title="Average Fare by Gender",
        chart_type="bar",
        business_question="Did fare paid differ between male and female passengers?",
        sql_query=(
            "SELECT sex, AVG(fare) AS avg_fare FROM cleaned_data "
            "GROUP BY sex ORDER BY avg_fare DESC"
        ),
        x_column="sex",
        y_column="avg_fare",
        aggregation="AVG",
        sort_order="desc",
        limit=10,
        x_label="Gender",
        y_label="Average Fare (USD)",
        plain_language_explanation="Shows the average fare paid by male and female passengers.",
    ),
    ChartSpec(
        title="Age Distribution of Passengers",
        chart_type="histogram",
        business_question="What is the age distribution of passengers?",
        sql_query="SELECT age FROM cleaned_data WHERE age IS NOT NULL",
        x_column="age",
        y_column=None,
        aggregation="NONE",
        sort_order="none",
        limit=None,
        x_label="Age",
        y_label=None,
        plain_language_explanation="Shows how passenger ages are spread across the dataset.",
    ),
]

LLM_INSIGHTS = [
    "Female passengers paid on average 3x more in fare than male passengers.",
    "The youngest passenger was just 1 year old, while the oldest was 71.",
    "Male passengers outnumbered female passengers by 11 to 9 in this sample.",
]


# ── Fixtures ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic.csv"
    path.write_text(SYNTHETIC_CSV, encoding="utf-8")
    return path


# ── Tests ─────────────────────────────────────────────────────────────────────────

def test_pipeline_happy_path_llm_succeeds(csv_path, mocker):
    """Full pipeline with mocked LLM: 3 LLM charts, 3 insights, transparency."""
    mocker.patch(
        "csv_dashboard.orchestrator.pipeline.plan_charts",
        return_value=LLM_SPECS,
    )
    mocker.patch(
        "csv_dashboard.orchestrator.pipeline.write_insights",
        return_value=LLM_INSIGHTS,
    )

    result = run(csv_path)

    assert isinstance(result, PipelineResult)
    assert len(result.charts) >= 3
    llm_charts = [c for c in result.charts if c.source == "llm"]
    assert len(llm_charts) == 3
    assert result.insights == LLM_INSIGHTS
    assert isinstance(result.transparency, dict)
    assert "has_changes" in result.transparency
    assert result.profile["filename"] == "synthetic.csv"
    assert result.profile["row_count"] == 20


def test_pipeline_uses_fallback_when_all_llm_specs_fail_sql(csv_path, mocker):
    """LLM returns specs but every SQL query fails: fallback fills charts, no insights."""
    bad_specs = [
        ChartSpec(
            title="Bad Chart One",
            chart_type="bar",
            business_question="This query references a column that does not exist.",
            sql_query=(
                "SELECT nonexistent_col, COUNT(*) AS cnt FROM cleaned_data "
                "GROUP BY nonexistent_col"
            ),
            x_column="nonexistent_col",
            y_column="cnt",
            aggregation="COUNT",
            sort_order="desc",
            plain_language_explanation="This spec will fail at SQL execution time.",
        ),
        ChartSpec(
            title="Bad Chart Two",
            chart_type="bar",
            business_question="Another query that will fail at SQL execution time.",
            sql_query=(
                "SELECT also_missing, COUNT(*) AS cnt FROM cleaned_data "
                "GROUP BY also_missing"
            ),
            x_column="also_missing",
            y_column="cnt",
            aggregation="COUNT",
            sort_order="desc",
            plain_language_explanation="This spec will also fail at SQL execution time.",
        ),
        ChartSpec(
            title="Bad Chart Three",
            chart_type="bar",
            business_question="A third query referencing a nonexistent column.",
            sql_query=(
                "SELECT ghost_column, COUNT(*) AS cnt FROM cleaned_data "
                "GROUP BY ghost_column"
            ),
            x_column="ghost_column",
            y_column="cnt",
            aggregation="COUNT",
            sort_order="desc",
            plain_language_explanation="A third spec that will fail at SQL execution time.",
        ),
    ]
    mocker.patch(
        "csv_dashboard.orchestrator.pipeline.plan_charts",
        return_value=bad_specs,
    )
    mock_writer = mocker.patch("csv_dashboard.orchestrator.pipeline.write_insights")

    result = run(csv_path)

    assert len(result.charts) >= 3
    assert all(c.source == "fallback" for c in result.charts)
    assert result.insights == []
    assert len(result.errors) == 3
    mock_writer.assert_not_called()


def test_pipeline_uses_fallback_when_llm_returns_empty(csv_path, mocker):
    """When plan_charts returns [], fallback engine fills charts; insights are empty."""
    mocker.patch(
        "csv_dashboard.orchestrator.pipeline.plan_charts",
        return_value=[],
    )
    mock_writer = mocker.patch(
        "csv_dashboard.orchestrator.pipeline.write_insights",
    )

    result = run(csv_path)

    assert isinstance(result, PipelineResult)
    assert len(result.charts) >= 3
    assert all(c.source == "fallback" for c in result.charts)
    assert result.insights == []
    mock_writer.assert_not_called()
