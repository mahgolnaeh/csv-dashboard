import json

import duckdb
from pydantic import ValidationError

from csv_dashboard.config import settings
from csv_dashboard.insights.chart_spec import ChartSpec, ChartSpecList
from csv_dashboard.insights.llm_client import LLMError, call_llm
from csv_dashboard.insights.prompts import (
    CHART_PLANNER_SYSTEM,
    build_planner_prompt,
    build_planner_retry_prompt,
)

# Map profiler semantic types to a DuckDB column type for the dry-run schema.
# boolean -> DOUBLE so AVG()/comparisons validate without false rejections;
# the dry-run only needs to catch column-name (binder) errors, not type errors.
_TYPE_MAP = {
    "numeric": "DOUBLE",
    "boolean": "DOUBLE",
    "datetime": "TIMESTAMP",
}


def _validation_con(profile: dict) -> duckdb.DuckDBPyConnection:
    """In-memory empty 'cleaned_data' table matching the profile's schema.

    Used only to EXPLAIN (parse + bind) generated SQL without fetching data,
    so a query referencing a non-existent column is caught before render.
    """
    cols = [
        f'"{name}" {_TYPE_MAP.get(info.get("semantic_type"), "VARCHAR")}'
        for name, info in profile.get("columns", {}).items()
    ]
    con = duckdb.connect()
    con.execute(f'CREATE TABLE "cleaned_data" ({", ".join(cols)})' if cols
                else 'CREATE TABLE "cleaned_data" (placeholder INTEGER)')
    return con


def plan_charts(profile: dict, quality_context: str) -> list[ChartSpec]:
    """Call Agent 1 to produce 3-5 validated chart specs. Returns [] on full failure.

    Each spec's SQL is dry-run with EXPLAIN against an empty schema-only copy of
    cleaned_data; binder errors (e.g. a column name rewritten to snake_case) feed
    the existing retry-once loop. After the final attempt, specs that still fail
    are dropped and the rest are returned.
    """
    prompt = build_planner_prompt(profile, quality_context)
    column_names = list(profile.get("columns", {}).keys())
    con = _validation_con(profile)

    try:
        for attempt in range(settings.max_llm_retries + 1):
            try:
                raw = call_llm(
                    CHART_PLANNER_SYSTEM,
                    prompt,
                    settings.chart_planner_model,
                    settings.llm_max_tokens,
                )
                raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                data = json.loads(raw)
                specs = ChartSpecList(**data).charts
            except (json.JSONDecodeError, ValidationError, LLMError) as e:
                if attempt < settings.max_llm_retries:
                    prompt = build_planner_retry_prompt(prompt, str(e), column_names)
                continue

            valid: list[ChartSpec] = []
            sql_errors: list[str] = []
            for spec in specs:
                try:
                    con.execute(f"EXPLAIN {spec.sql_query}")
                    valid.append(spec)
                except Exception as e:  # broad on purpose: any bind/parse failure -> retry the spec
                    sql_errors.append(f"Chart '{spec.title}': {e}")

            if not sql_errors:
                return valid
            if attempt < settings.max_llm_retries:
                prompt = build_planner_retry_prompt(
                    prompt, "\n".join(sql_errors), column_names
                )
                continue
            return valid  # final attempt: keep what works, drop the rest

        return []
    finally:
        con.close()
