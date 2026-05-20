import json

from pydantic import ValidationError

from csv_dashboard.config import settings
from csv_dashboard.insights.chart_spec import ChartSpec, ChartSpecList
from csv_dashboard.insights.llm_client import LLMError, call_llm
from csv_dashboard.insights.prompts import (
    CHART_PLANNER_SYSTEM,
    build_planner_prompt,
    build_planner_retry_prompt,
)


def plan_charts(profile: dict, quality_context: str) -> list[ChartSpec]:
    """Call Agent 1 to produce 3-5 validated chart specs. Returns [] on full failure."""
    prompt = build_planner_prompt(profile, quality_context)
    column_names = list(profile.get("columns", {}).keys())

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
            return ChartSpecList(**data).charts
        except (json.JSONDecodeError, ValidationError, LLMError) as e:
            if attempt < settings.max_llm_retries:
                prompt = build_planner_retry_prompt(prompt, str(e), column_names)
            continue

    return []
