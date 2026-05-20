"""
Tests for agents/insight_writer.py.
All LLM calls are mocked -- no network, no API key needed.

build_insight_prompt() is real code (not mocked), so fixtures use genuine
ChartSpec objects and small pd.DataFrames that the prompt builder can
serialize.
"""

import json

import pandas as pd
import pytest

from csv_dashboard.agents.insight_writer import write_insights
from csv_dashboard.insights.chart_spec import ChartSpec
from csv_dashboard.insights.llm_client import LLMError


# ── Fixtures ────────────────────────────────────────────────────────────────────

def _bar_spec(title: str, question: str, sql: str, x: str, y: str) -> ChartSpec:
    return ChartSpec(
        title=title,
        chart_type="bar",
        business_question=question,
        sql_query=sql,
        x_column=x,
        y_column=y,
        aggregation="COUNT",
        sort_order="desc",
        plain_language_explanation=f"Shows {title.lower()} counts from the dataset.",
    )


SURVIVAL_BY_GENDER = _bar_spec(
    title="Survival by Gender",
    question="How does survival rate differ by gender?",
    sql="SELECT sex, COUNT(*) AS cnt FROM cleaned_data GROUP BY sex ORDER BY cnt DESC",
    x="sex",
    y="cnt",
)

SURVIVAL_BY_CLASS = _bar_spec(
    title="Survival by Passenger Class",
    question="Which passenger class had the highest survival rate?",
    sql=(
        "SELECT pclass, COUNT(*) AS cnt FROM cleaned_data "
        "GROUP BY pclass ORDER BY cnt DESC"
    ),
    x="pclass",
    y="cnt",
)

SAMPLE_RESULTS = [
    (
        SURVIVAL_BY_GENDER,
        pd.DataFrame({"sex": ["female", "male"], "cnt": [233, 109]}),
    ),
    (
        SURVIVAL_BY_CLASS,
        pd.DataFrame({"pclass": [1, 2, 3], "cnt": [136, 87, 119]}),
    ),
]

VALID_LLM_RESPONSE = json.dumps({
    "insights": [
        "Women survived at a rate of 74%, compared to 19% for men.",
        "First-class passengers had a 63% survival rate, more than double third-class (24%).",
        "Overall, 342 of 891 passengers survived -- a survival rate of 38%.",
    ]
})


# ── Tests ───────────────────────────────────────────────────────────────────────

def test_write_insights_returns_strings_on_valid_llm_response(mocker):
    """Valid JSON from LLM produces a list of plain-English insight strings."""
    mocker.patch(
        "csv_dashboard.agents.insight_writer.call_llm",
        return_value=VALID_LLM_RESPONSE,
    )

    result = write_insights(SAMPLE_RESULTS)

    assert len(result) == 3
    assert all(isinstance(s, str) for s in result)
    assert "74%" in result[0]


def test_write_insights_returns_empty_on_llm_error(mocker):
    """LLMError from call_llm returns empty list without raising."""
    mocker.patch(
        "csv_dashboard.agents.insight_writer.call_llm",
        side_effect=LLMError("OpenRouter unreachable"),
    )

    result = write_insights(SAMPLE_RESULTS)

    assert result == []


def test_write_insights_returns_empty_on_malformed_json(mocker):
    """Malformed JSON from LLM returns empty list without raising."""
    mocker.patch(
        "csv_dashboard.agents.insight_writer.call_llm",
        return_value="not valid json { broken",
    )

    result = write_insights(SAMPLE_RESULTS)

    assert result == []


def test_write_insights_returns_empty_immediately_for_empty_input(mocker):
    """Empty chart_results returns [] immediately without calling the LLM."""
    mock_llm = mocker.patch("csv_dashboard.agents.insight_writer.call_llm")

    result = write_insights([])

    assert result == []
    mock_llm.assert_not_called()


def test_write_insights_handles_bare_list_llm_response(mocker):
    """LLM returning a bare JSON array (not wrapped in a dict) is accepted."""
    mocker.patch(
        "csv_dashboard.agents.insight_writer.call_llm",
        return_value=json.dumps([
            "Insight A from bare list.",
            "Insight B from bare list.",
            "Insight C from bare list.",
        ]),
    )

    result = write_insights(SAMPLE_RESULTS)

    assert len(result) == 3
    assert result[0] == "Insight A from bare list."


def test_write_insights_caps_output_at_five(mocker):
    """More than 5 insights from the LLM are capped to 5."""
    mocker.patch(
        "csv_dashboard.agents.insight_writer.call_llm",
        return_value=json.dumps({
            "insights": [
                "Insight one.",
                "Insight two.",
                "Insight three.",
                "Insight four.",
                "Insight five.",
                "Insight six -- should be dropped.",
                "Insight seven -- should be dropped.",
            ]
        }),
    )

    result = write_insights(SAMPLE_RESULTS)

    assert len(result) == 5
    assert "six" not in " ".join(result)
    assert "seven" not in " ".join(result)
