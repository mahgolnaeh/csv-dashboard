from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from csv_dashboard.agents.chart_planner import plan_charts
from csv_dashboard.agents.insight_writer import write_insights
from csv_dashboard.charts.engine import generate_charts as fallback_charts
from csv_dashboard.charts.renderer import render as render_chart
from csv_dashboard.ingestion.loader import load_csv
from csv_dashboard.insights.chart_spec import ChartSpec
from csv_dashboard.profiling.profiler import profile_dataframe
from csv_dashboard.quality.data_quality import run as run_quality
from csv_dashboard.transparency.transparency import build as build_transparency


@dataclass
class ChartArtifact:
    title: str
    figure: go.Figure
    source: str  # "llm" or "fallback"
    explanation: str = ""


@dataclass
class PipelineResult:
    charts: list[ChartArtifact]
    insights: list[str]
    transparency: dict
    profile: dict
    errors: list[str] = field(default_factory=list)


def run(csv_path: str | Path) -> PipelineResult:
    """Run the full 8-step pipeline. Always returns a PipelineResult."""
    filename = Path(csv_path).name
    errors: list[str] = []

    # Step 1: Load CSV into DuckDB (raw_data table).
    # FileLoadError propagates intentionally -- no CSV, no dashboard.
    con = load_csv(csv_path)

    try:
        # Step 2: Data quality -- creates cleaned_data VIEW
        dq = run_quality(con)

        # Step 3: Profile the cleaned data
        df = con.execute('SELECT * FROM "cleaned_data"').df()
        profile = profile_dataframe(df)
        profile["filename"] = filename

        # Step 4: Agent 1 -- Chart Planner (LLM)
        specs = plan_charts(profile, dq["llm_context"])

        # Step 5: Execute each spec's SQL and render
        chart_results: list[tuple[ChartSpec, pd.DataFrame]] = []
        charts: list[ChartArtifact] = []
        for spec in specs:
            try:
                result_df = con.execute(spec.sql_query).df()
                fig = render_chart(spec, result_df)
                charts.append(ChartArtifact(
                    title=spec.title,
                    figure=fig,
                    source="llm",
                    explanation=spec.plain_language_explanation,
                ))
                chart_results.append((spec, result_df))
            except Exception as e:
                errors.append(f"Chart '{spec.title}' failed: {e}")

        # Step 6: Fallback if LLM produced fewer than 3 usable charts
        if len(charts) < 3:
            for fc in fallback_charts(df, filename):
                charts.append(ChartArtifact(
                    title=fc["title"],
                    figure=fc["figure"],
                    source="fallback",
                ))

        # Step 7: Agent 2 -- Insight Writer (LLM, only when there are LLM chart results)
        insights = write_insights(chart_results) if chart_results else []

        # Step 8: Transparency report
        transparency = build_transparency(dq["quality_report"])

    finally:
        con.close()

    return PipelineResult(
        charts=charts,
        insights=insights,
        transparency=transparency,
        profile=profile,
        errors=errors,
    )
