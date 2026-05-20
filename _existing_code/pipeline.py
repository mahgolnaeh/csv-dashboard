"""
pipeline.py
-----------
Full pipeline: CSV → cleaned data → profiling → LLM chart specs → charts.

Flow:
  Step 1  CSV upload           read_csv()
  Step 2  Data quality         data_quality.run()
  Step 3  DuckDB profiling     _profile()
  Step 4  LLM generates specs  _ask_llm()   ← uses dataset summary + quality context
  Step 5  Pydantic validation  ChartSpec()
  Step 6  SQL safety check     inside ChartSpec validators
  Step 7  DuckDB executes SQL  _execute()
          └─ on fail → retry LLM once
          └─ on fail again → fallback to chart_engine
  Step 8  Plotly renders       _render()

Usage:
    from pipeline import run
    charts = run("titanic.csv")
    for c in charts:
        c["figure"].show()
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any

import duckdb
import pandas as pd
from anthropic import Anthropic
from pydantic import ValidationError

# ── local modules ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
import data_quality
from profiler import profile_dataframe
import transparency
from chart_engine import generate_charts
from chart_spec import ChartSpec, ChartSpecList
import plotly.graph_objects as go
import plotly.express as px


# ── Config ─────────────────────────────────────────────────────────────────────

LLM_MODEL        = "claude-haiku-4-5-20251001"
LLM_MAX_TOKENS   = 2048
MAX_LLM_RETRIES  = 1          # one retry before fallback
TOP_N_CATEGORIES = 10         # passed to LLM as a constraint
SAMPLE_ROWS      = 3          # rows shown to LLM as examples


# ── Public entry point ─────────────────────────────────────────────────────────

def run(
    csv_path: str,
    show: bool = False,
    verbose: bool = True,
) -> list[dict]:
    """
    Run the full pipeline on a CSV file.

    Returns a list of dicts:
        {
          "title":   str,
          "figure":  plotly.graph_objects.Figure,
          "source":  "llm" | "fallback",
          "rule":    str,          # only for fallback charts
        }
    """
    filename = os.path.basename(csv_path)
    _log(verbose, f"\n{'─'*55}")
    _log(verbose, f"  Pipeline start: {filename}")
    _log(verbose, f"{'─'*55}")

    # ── Step 1: DuckDB loads raw CSV ──────────────────────────────────────────
    _log(verbose, "\n[1] Loading CSV into DuckDB...")
    try:
        con = duckdb.connect()
        con.execute(
            f"CREATE OR REPLACE TABLE raw_data AS "
            f"SELECT * FROM read_csv_auto('{csv_path}', header=true)"
        )
        row_count = con.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
        col_count = len(con.execute("DESCRIBE raw_data").fetchall())
        _log(verbose, f"    {row_count:,} rows × {col_count} columns")
    except Exception as e:
        raise RuntimeError(f"Could not load CSV into DuckDB: {e}") from e

    # ── Step 2: Data quality — analyzes raw_data, creates cleaned_data VIEW ───
    _log(verbose, "\n[2] Running data quality check...")
    dq = data_quality.run(con, raw_table="raw_data")
    view_name  = dq["view_name"]     # "cleaned_data"
    clean_cols = dq["clean_columns"]
    if dq["dropped_cols"]:
        _log(verbose, f"    Dropped columns: {dq['dropped_cols']}")
    warns = [r for r in dq["quality_report"] if r["severity"] == "warn"]
    if warns:
        _log(verbose, f"    Warnings: {len(warns)} issue(s) — passed to LLM")

    # Build transparency report — shown to user in dashboard
    transparency_report = transparency.build(dq["quality_report"])
    if verbose and transparency_report["has_changes"]:
        _log(verbose, transparency_report["plain_text"])

    # ── Step 3: Profiling — queries the cleaned_data VIEW ─────────────────────
    _log(verbose, "\n[3] Profiling cleaned_data view...")
    df = con.execute('SELECT * FROM "cleaned_data"').df()
    profile = profile_dataframe(df)
    profile["filename"] = filename
    _log(verbose, f"    {profile['column_count']} columns profiled — "
                  f"semantic types: {profile['semantic_type_summary']}")

    # ── Step 4: LLM generates chart specs ─────────────────────────────────────
    _log(verbose, "\n[4] Asking LLM for chart specs...")
    prompt = _build_prompt(profile, dq["llm_context"])
    specs, llm_error = _ask_llm_with_validation(prompt, verbose)

    # ── Steps 5–7 + retry + fallback ──────────────────────────────────────────
    charts: list[dict] = []

    if specs:
        _log(verbose, f"    {len(specs)} valid spec(s) received")
        for spec in specs:
            fig, source = _execute_and_render(spec, con, df, prompt, verbose)
            if fig:
                charts.append({"title": spec.title, "figure": fig, "source": source})
    else:
        _log(verbose, f"    LLM failed ({llm_error}) — using fallback for all charts")

    # ── Fallback for any missing charts ───────────────────────────────────────
    if len(charts) < 3:
        _log(verbose, f"\n[fallback] LLM produced {len(charts)} chart(s) — "
                      f"running deterministic chart_engine for the rest...")
        fallback_charts = generate_charts(df, filename)
        for fc in fallback_charts:
            charts.append({
                "title":  fc["title"],
                "figure": fc["figure"],
                "source": "fallback",
                "rule":   fc["rule"],
            })

    _log(verbose, f"\n{'─'*55}")
    _log(verbose, f"  Done. {len(charts)} chart(s) ready.")
    _log(verbose, f"  Transparency: {len(transparency_report['sentences'])} change(s) reported to user.")
    _log(verbose, f"  LLM: {sum(1 for c in charts if c['source']=='llm')}  "
                  f"Fallback: {sum(1 for c in charts if c['source']=='fallback')}")
    _log(verbose, f"{'─'*55}\n")

    if show:
        for c in charts:
            c["figure"].show()

    con.close()
    return charts, transparency_report


# ── Step 4: LLM prompt builder ─────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a data analyst generating chart specifications for a business dashboard.
The audience is non-technical consultants. Keep charts simple and meaningful.

Rules:
- Use ONLY column names that exist in the schema.
- Use ONLY SELECT queries. Table name is always: cleaned_data
- Avoid identifier columns (id, uuid, index).
- For categorical columns with many values, use TOP {top_n} only.
- Prefer charts that answer real business questions.
- Return ONLY valid JSON. No markdown, no explanation outside the JSON.

Return this exact structure:
{{
  "charts": [
    {{
      "title": "...",
      "chart_type": "bar|line|scatter|histogram|heatmap",
      "business_question": "...",
      "sql_query": "SELECT ... FROM data ...",
      "x_column": "...",
      "y_column": "...",
      "color_column": null,
      "aggregation": "COUNT|AVG|SUM|MEDIAN|MIN|MAX|NONE",
      "sort_order": "asc|desc|none",
      "limit": 10,
      "x_label": "...",
      "y_label": "...",
      "plain_language_explanation": "..."
    }}
  ]
}}
""".format(top_n=TOP_N_CATEGORIES)


def _build_prompt(profile: dict, quality_context: str) -> str:
    # Build a compact column list — only what LLM needs
    col_summary = []
    for name, info in profile["columns"].items():
        entry = {
            "name":          name,
            "semantic_type": info["semantic_type"],
            "missing_pct":   info["missing_pct"],
            "unique_count":  info["unique_count"],
        }
        if info.get("numeric_summary"):
            ns = info["numeric_summary"]
            entry["stats"] = {
                "min":    ns["min"],   "max": ns["max"],
                "mean":   ns["mean"],  "median": ns["median"],
                "std":    ns["std"],
                "skewness":          ns["skewness"],
                "outlier_count_iqr": ns["outlier_count_iqr"],
            }
        if info.get("sample_values"):
            entry["sample_values"] = info["sample_values"]
        if info.get("warning"):
            entry["warning"] = info["warning"]
        col_summary.append(entry)

    warnings_text = ""
    if profile.get("warnings"):
        warnings_text = f"\nData warnings: {json.dumps(profile['warnings'])}\n"

    return (
        f"Dataset: {profile['filename']}\n"
        f"Rows: {profile['row_count']:,}  |  Columns: {profile['column_count']}\n"
        f"Duplicate rows: {profile.get('duplicate_row_count', 0)}\n\n"
        f"Column types available:\n"
        f"  numeric:     {profile['semantic_type_summary']['numeric']}\n"
        f"  categorical: {profile['semantic_type_summary']['categorical']}\n"
        f"  datetime:    {profile['semantic_type_summary']['datetime']}\n"
        f"  boolean:     {profile['semantic_type_summary']['boolean']}\n"
        f"  identifier:  {profile['semantic_type_summary']['identifier']} (DO NOT USE)\n"
        f"  text:        {profile['semantic_type_summary']['text']} (DO NOT USE)\n\n"
        f"Column details:\n{json.dumps(col_summary, indent=2)}\n"
        f"{warnings_text}"
        f"\n{quality_context}\n\n"
        f"Generate 3 to 5 useful chart specs for this dataset."
    )


def _build_retry_prompt(original_prompt: str, error_msg: str, column_names: list[str]) -> str:
    return (
        f"{original_prompt}\n\n"
        f"---\n"
        f"Your previous response had this error:\n{error_msg}\n\n"
        f"Available column names: {column_names}\n"
        f"Please fix the issue and return a corrected JSON response."
    )


# ── Step 4+5+6: LLM call with Pydantic validation ─────────────────────────────

def _ask_llm_with_validation(
    prompt: str,
    verbose: bool,
) -> tuple[list[ChartSpec] | None, str]:
    """
    Call LLM, parse JSON, validate with Pydantic.
    Returns (specs, error_message). specs is None if validation failed.
    """
    client = Anthropic()

    for attempt in range(MAX_LLM_RETRIES + 1):
        try:
            response = client.messages.create(
                model=LLM_MODEL,
                max_tokens=LLM_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()

            # Strip markdown fences if present
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

            data = json.loads(raw)
            spec_list = ChartSpecList(**data)
            return spec_list.charts, ""

        except json.JSONDecodeError as e:
            err = f"JSON parse error: {e}"
        except ValidationError as e:
            err = f"Pydantic validation error: {e.errors()[0]['msg']}"
        except Exception as e:
            err = f"LLM call error: {e}"

        _log(verbose, f"    Attempt {attempt+1} failed: {err}")

        if attempt < MAX_LLM_RETRIES:
            _log(verbose, f"    Retrying LLM...")
            # Build a correction prompt for the retry
            prompt = _build_retry_prompt(prompt, err, [])

    return None, err


# ── Step 7: Execute SQL + render ───────────────────────────────────────────────

def _execute_and_render(
    spec: ChartSpec,
    con: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    original_prompt: str,
    verbose: bool,
) -> tuple[go.Figure | None, str]:
    """
    Execute SQL for one spec.
    On failure: retry LLM once for this spec, then fallback.
    Returns (figure, source) where source is "llm" or "fallback".
    """
    for attempt in range(MAX_LLM_RETRIES + 1):
        try:
            result_df = con.execute(spec.sql_query).df()
            fig = _render(spec, result_df)
            return fig, "llm"

        except Exception as e:
            err = str(e)
            _log(verbose, f"    SQL failed for '{spec.title}': {err}")

            if attempt < MAX_LLM_RETRIES:
                _log(verbose, f"    Retrying LLM for this spec...")
                retry_prompt = _build_retry_prompt(
                    original_prompt, err, list(df.columns)
                )
                new_specs, _ = _ask_llm_with_validation(retry_prompt, verbose)
                if new_specs:
                    # Use the first spec from the retry that matches this title
                    matching = next(
                        (s for s in new_specs if s.title == spec.title), new_specs[0]
                    )
                    spec = matching

    # Both attempts failed — use fallback chart_engine for this column
    _log(verbose, f"    Fallback for '{spec.title}'")
    col = spec.x_column or spec.y_column
    if col and col in df.columns:
        fallback = generate_charts(df[[col]], col)
        if fallback:
            return fallback[0]["figure"], "fallback"

    return None, "fallback"


# ── Step 8: Render ─────────────────────────────────────────────────────────────

PLOTLY_TEMPLATE = "plotly_white"
COLORS = px.colors.qualitative.Safe


def _render(spec: ChartSpec, df: pd.DataFrame) -> go.Figure:
    """Build a Plotly figure from a validated ChartSpec + query result."""
    ct   = spec.chart_type
    xcol = spec.x_column
    ycol = spec.y_column
    ccol = spec.color_column

    # Sort if requested
    if spec.sort_order != "none" and ycol and ycol in df.columns:
        df = df.sort_values(ycol, ascending=(spec.sort_order == "asc"))

    if ct == "bar":
        fig = px.bar(
            df, x=xcol, y=ycol, color=ccol,
            labels={xcol: spec.x_label or xcol, ycol: spec.y_label or ycol},
            color_discrete_sequence=COLORS,
            template=PLOTLY_TEMPLATE,
        )

    elif ct == "line":
        fig = px.line(
            df, x=xcol, y=ycol, color=ccol,
            labels={xcol: spec.x_label or xcol, ycol: spec.y_label or ycol},
            template=PLOTLY_TEMPLATE,
        )

    elif ct == "scatter":
        fig = px.scatter(
            df, x=xcol, y=ycol, color=ccol,
            labels={xcol: spec.x_label or xcol, ycol: spec.y_label or ycol},
            trendline="ols",
            template=PLOTLY_TEMPLATE,
        )

    elif ct == "histogram":
        fig = px.histogram(
            df, x=xcol,
            labels={xcol: spec.x_label or xcol},
            template=PLOTLY_TEMPLATE,
            nbins=30,
        )

    elif ct == "heatmap":
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        corr = df[numeric_cols].corr()
        fig = px.imshow(
            corr, color_continuous_scale="RdBu",
            zmin=-1, zmax=1, aspect="auto",
            template=PLOTLY_TEMPLATE,
        )

    else:
        # Unknown type — safe fallback: bar
        fig = px.bar(df, x=xcol, y=ycol, template=PLOTLY_TEMPLATE)

    fig.update_layout(
        title=dict(text=spec.title, font=dict(size=16)),
        margin=dict(t=50, b=40, l=40, r=20),
        height=400,
    )

    # Add explanation as a subtitle annotation
    if spec.plain_language_explanation:
        fig.add_annotation(
            text=spec.plain_language_explanation,
            xref="paper", yref="paper",
            x=0, y=-0.12, showarrow=False,
            font=dict(size=12, color="gray"),
            xanchor="left",
        )

    return fig


# ── Utility ────────────────────────────────────────────────────────────────────

def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(msg)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py path/to/file.csv")
        sys.exit(1)

    charts = run(sys.argv[1], show=True, verbose=True)
    print(f"\nTotal charts: {len(charts)}")
    for i, c in enumerate(charts, 1):
        print(f"  {i:>2}. [{c['source'].upper():8}] {c['title']}")
