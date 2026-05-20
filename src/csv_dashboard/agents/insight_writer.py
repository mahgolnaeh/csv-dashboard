import json

import pandas as pd

from csv_dashboard.config import settings
from csv_dashboard.insights.chart_spec import ChartSpec
from csv_dashboard.insights.llm_client import LLMError, call_llm
from csv_dashboard.insights.prompts import INSIGHT_WRITER_SYSTEM, build_insight_prompt


def write_insights(
    chart_results: list[tuple[ChartSpec, pd.DataFrame]],
) -> list[str]:
    """Call Agent 2 to produce 3-5 plain-English insights. Returns [] on failure."""
    if not chart_results:
        return []
    try:
        prompt = build_insight_prompt(chart_results)
        raw = call_llm(
            INSIGHT_WRITER_SYSTEM,
            prompt,
            settings.insight_writer_model,
            settings.llm_max_tokens,
        )
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        insights = data.get("insights", []) if isinstance(data, dict) else data
        return [str(s) for s in insights if isinstance(s, str)][:5]
    except (LLMError, json.JSONDecodeError):
        return []
