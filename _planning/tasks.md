# Tasks: CSV Dashboard MVP

> Executable task list. Each task has a clear input, output, and "done" criterion.
> Tasks are ordered. `[P]` = can run in parallel with the previous task.

---

## Phase 1: Foundation

### T-001: Initialize project with uv
- **Action:** `uv init csv-dashboard --package` (or create `pyproject.toml` manually).
- **Output:** `pyproject.toml`, `src/csv_dashboard/__init__.py`.
- **Done when:** `uv run python -c "import csv_dashboard"` works.

### T-002: Add dependencies to pyproject.toml
- **Action:** Add to `[project] dependencies`:
  ```
  duckdb>=1.0
  pandas>=2.0
  numpy>=1.24
  pydantic>=2.0
  pydantic-settings>=2.0
  httpx>=0.25
  plotly>=5.18
  scipy>=1.11
  streamlit>=1.30
  python-dotenv>=1.0
  structlog>=24.0
  ```
  And to `[dependency-groups] dev`:
  ```
  pytest>=8.0
  pytest-mock>=3.12
  pytest-cov>=4.1
  ruff>=0.4
  ```
- **Output:** Updated `pyproject.toml`.
- **Done when:** `uv sync` completes without errors.

### T-003: Create folder structure
- **Action:** Create all folders and empty `__init__.py` files as listed in `plan.md` Section 2.
- **Output:** Empty module skeleton.
- **Done when:** `find src tests -type d` matches the plan.

### T-004: Create config.py
- **Action:** Write `src/csv_dashboard/config.py`:
  ```python
  from pydantic_settings import BaseSettings, SettingsConfigDict

  class Settings(BaseSettings):
      model_config = SettingsConfigDict(env_file=".env", extra="ignore")

      openrouter_api_key: str
      chart_planner_model: str = "anthropic/claude-haiku-4.5"
      insight_writer_model: str = "anthropic/claude-haiku-4.5"
      max_llm_retries: int = 1
      llm_max_tokens: int = 2048
      top_n_categories: int = 10
      missing_threshold: float = 0.40
      correlation_threshold: float = 0.40
      heatmap_threshold: float = 0.50

  settings = Settings()
  ```
- **Output:** `src/csv_dashboard/config.py`.
- **Done when:** `from csv_dashboard.config import settings` works with a valid `.env`.

### T-005: Create .env.example and .gitignore
- **Action:**
  - `.env.example`: `OPENROUTER_API_KEY=your_key_here`
  - `.gitignore`: include `.env`, `__pycache__`, `.pytest_cache`, `.venv`, `*.egg-info`
- **Output:** `.env.example`, `.gitignore`.
- **Done when:** Files exist; `.env` is git-ignored.

### T-006: Initial README
- **Action:** Write a minimal `README.md`:
  - Project title and one-paragraph description.
  - "Status: in development" badge.
  - Placeholder sections: Setup, Run, Test, Docker, Architecture, License.
- **Output:** `README.md`.
- **Done when:** File exists and renders on GitHub.

---

## Phase 2: Move existing modules

### T-010: Move chart_engine.py
- **Action:** Copy `chart_engine.py` to `src/csv_dashboard/charts/engine.py`. Update imports inside if needed.
- **Output:** `src/csv_dashboard/charts/engine.py`.
- **Done when:** `from csv_dashboard.charts.engine import generate_charts` works.

### T-011: Move data_quality.py
- **Action:** Copy to `src/csv_dashboard/quality/data_quality.py`.
- **Output:** File in new location.
- **Done when:** `from csv_dashboard.quality.data_quality import run` works.

### T-012: Move profiler.py
- **Action:** Copy to `src/csv_dashboard/profiling/profiler.py`.
- **Output:** File in new location.
- **Done when:** `from csv_dashboard.profiling.profiler import profile_dataframe` works.

### T-013: Move chart_spec.py
- **Action:** Copy to `src/csv_dashboard/insights/chart_spec.py`.
- **Output:** File in new location.
- **Done when:** `from csv_dashboard.insights.chart_spec import ChartSpec, ChartSpecList` works.

### T-014: Move transparency.py
- **Action:** Copy to `src/csv_dashboard/transparency/transparency.py`.
- **Output:** File in new location.
- **Done when:** `from csv_dashboard.transparency.transparency import build, show_in_streamlit` works.

### T-015: Add public exports in __init__.py files
- **Action:** Each module's `__init__.py` re-exports its public functions:
  ```python
  # src/csv_dashboard/quality/__init__.py
  from .data_quality import run
  __all__ = ["run"]
  ```
- **Output:** All `__init__.py` files populated.
- **Done when:** Short imports work: `from csv_dashboard.quality import run`.

### T-016: Smoke-test all imports
- **Action:** Write a one-line test:
  ```python
  # tests/test_imports.py
  def test_all_modules_import():
      from csv_dashboard.charts.engine import generate_charts
      from csv_dashboard.quality.data_quality import run
      from csv_dashboard.profiling.profiler import profile_dataframe
      from csv_dashboard.insights.chart_spec import ChartSpec, ChartSpecList
      from csv_dashboard.transparency.transparency import build
  ```
- **Output:** Test passes.
- **Done when:** `uv run pytest tests/test_imports.py` is green.

---

## Phase 3: Ingestion module

### T-020: Create loader.py
- **Action:** Write `src/csv_dashboard/ingestion/loader.py`:
  ```python
  import duckdb
  from pathlib import Path

  class FileLoadError(Exception):
      """Raised when a CSV cannot be loaded."""

  def load_csv(path: str | Path) -> duckdb.DuckDBPyConnection:
      """Load a CSV into DuckDB as table 'raw_data'."""
      path_str = str(path)
      try:
          con = duckdb.connect()
          con.execute(
              "CREATE OR REPLACE TABLE raw_data AS "
              f"SELECT * FROM read_csv_auto('{path_str}', header=true)"
          )
          return con
      except Exception as e:
          raise FileLoadError(f"Could not load CSV: {e}") from e
  ```
- **Output:** `src/csv_dashboard/ingestion/loader.py`.
- **Done when:** Loading a valid CSV returns a connection with `raw_data` registered.

### T-021: Test loader
- **Action:** Write `tests/test_loader.py`:
  - Test loading a valid CSV.
  - Test that loading a nonexistent file raises `FileLoadError`.
  - Test that loading a malformed file raises `FileLoadError`.
- **Output:** `tests/test_loader.py`.
- **Done when:** All three tests pass.

---

## Phase 4: OpenRouter LLM client

### T-030: Create llm_client.py
- **Action:** Write `src/csv_dashboard/insights/llm_client.py`:
  ```python
  import httpx
  import structlog
  from csv_dashboard.config import settings

  log = structlog.get_logger()

  class LLMError(Exception):
      """Raised when an LLM call fails after all retries."""

  OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

  def call_llm(
      system_prompt: str,
      user_prompt: str,
      model: str,
      max_tokens: int = 2048,
  ) -> str:
      headers = {
          "Authorization": f"Bearer {settings.openrouter_api_key}",
          "Content-Type": "application/json",
      }
      payload = {
          "model": model,
          "max_tokens": max_tokens,
          "messages": [
              {"role": "system", "content": system_prompt},
              {"role": "user",   "content": user_prompt},
          ],
      }
      try:
          r = httpx.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
          r.raise_for_status()
          data = r.json()
          return data["choices"][0]["message"]["content"].strip()
      except (httpx.HTTPError, KeyError, ValueError) as e:
          log.error("llm_call_failed", model=model, error=str(e))
          raise LLMError(f"LLM call failed: {e}") from e
  ```
- **Output:** `src/csv_dashboard/insights/llm_client.py`.
- **Done when:** Function callable; raises `LLMError` on bad key.

### T-031: Test llm_client with mock
- **Action:** Write `tests/test_llm_client.py` using `pytest-mock`:
  - Mock `httpx.post` to return a fake response → assert function returns the content.
  - Mock to raise `httpx.HTTPError` → assert `LLMError` raised.
  - Mock to return malformed JSON → assert `LLMError` raised.
- **Output:** `tests/test_llm_client.py`.
- **Done when:** All three tests pass.

---

## Phase 5: Prompts and agents

### T-040: Create prompts.py
- **Action:** Write `src/csv_dashboard/insights/prompts.py`:
  - `CHART_PLANNER_SYSTEM`: full system prompt for Agent 1 (chart spec generation).
    Key rules from constitution: cleaned_data table, no identifier/text columns,
    top-N for categoricals, prefer median over mean for skewed data, JSON-only output.
  - `INSIGHT_WRITER_SYSTEM`: full system prompt for Agent 2.
    Rules: plain English, reference actual numbers, one or two sentences per insight,
    3-5 insights total, no jargon.
  - `build_planner_prompt(profile, quality_context) -> str`.
  - `build_planner_retry_prompt(original, error, columns) -> str`.
  - `build_insight_prompt(chart_results) -> str`:
    Summarize each result_df: top 5 rows, column statistics.
- **Output:** `src/csv_dashboard/insights/prompts.py`.
- **Done when:** All three builder functions return formatted strings.

### T-041: Create chart_planner.py
- **Action:** Write `src/csv_dashboard/agents/chart_planner.py`:
  ```python
  import json
  from pydantic import ValidationError
  from csv_dashboard.config import settings
  from csv_dashboard.insights.llm_client import call_llm, LLMError
  from csv_dashboard.insights.chart_spec import ChartSpec, ChartSpecList
  from csv_dashboard.insights.prompts import (
      CHART_PLANNER_SYSTEM,
      build_planner_prompt,
      build_planner_retry_prompt,
  )

  def plan_charts(profile: dict, quality_context: str) -> list[ChartSpec]:
      prompt = build_planner_prompt(profile, quality_context)
      column_names = list(profile.get("columns", {}).keys())

      for attempt in range(settings.max_llm_retries + 1):
          try:
              raw = call_llm(
                  CHART_PLANNER_SYSTEM, prompt,
                  settings.chart_planner_model, settings.llm_max_tokens,
              )
              raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
              data = json.loads(raw)
              return ChartSpecList(**data).charts
          except (json.JSONDecodeError, ValidationError, LLMError) as e:
              if attempt < settings.max_llm_retries:
                  prompt = build_planner_retry_prompt(prompt, str(e), column_names)
              continue
      return []
  ```
- **Output:** `src/csv_dashboard/agents/chart_planner.py`.
- **Done when:** Function returns a list of valid `ChartSpec` objects or empty on failure.

### T-042: Create insight_writer.py
- **Action:** Write `src/csv_dashboard/agents/insight_writer.py`:
  ```python
  import json
  import pandas as pd
  from csv_dashboard.config import settings
  from csv_dashboard.insights.llm_client import call_llm, LLMError
  from csv_dashboard.insights.chart_spec import ChartSpec
  from csv_dashboard.insights.prompts import (
      INSIGHT_WRITER_SYSTEM,
      build_insight_prompt,
  )

  def write_insights(
      chart_results: list[tuple[ChartSpec, pd.DataFrame]],
  ) -> list[str]:
      if not chart_results:
          return []
      try:
          prompt = build_insight_prompt(chart_results)
          raw = call_llm(
              INSIGHT_WRITER_SYSTEM, prompt,
              settings.insight_writer_model, settings.llm_max_tokens,
          )
          raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
          data = json.loads(raw)
          insights = data.get("insights", []) if isinstance(data, dict) else data
          return [str(s) for s in insights if isinstance(s, str)][:5]
      except (LLMError, json.JSONDecodeError):
          return []
  ```
- **Output:** `src/csv_dashboard/agents/insight_writer.py`.
- **Done when:** Function returns 3-5 strings for valid input, empty list on failure.

### T-043: Test chart_planner with mock
- **Action:** Write `tests/test_chart_planner.py`:
  - Mock `call_llm` to return valid JSON → assert returns 3 ChartSpec.
  - Mock to return malformed JSON → assert returns empty (after retry).
  - Mock to raise LLMError → assert returns empty.
- **Output:** `tests/test_chart_planner.py`.
- **Done when:** All three tests pass.

### T-044: Test insight_writer with mock
- **Action:** Write `tests/test_insight_writer.py`:
  - Mock LLM to return JSON list of insights → assert correct output.
  - Mock to raise LLMError → assert returns empty.
- **Output:** `tests/test_insight_writer.py`.
- **Done when:** Both tests pass.

---

## Phase 6: Renderer

### T-050: Create renderer.py
- **Action:** Extract `_render` from existing `pipeline.py` into `src/csv_dashboard/charts/renderer.py`:
  ```python
  import plotly.express as px
  import plotly.graph_objects as go
  import pandas as pd
  from csv_dashboard.insights.chart_spec import ChartSpec

  PLOTLY_TEMPLATE = "plotly_white"
  COLORS = px.colors.qualitative.Safe

  def render(spec: ChartSpec, df: pd.DataFrame) -> go.Figure:
      # Logic identical to current _render in pipeline.py
      ...
  ```
- **Output:** `src/csv_dashboard/charts/renderer.py`.
- **Done when:** A figure renders without errors for each chart_type.

### T-051: Test renderer
- **Action:** Write `tests/test_renderer.py`:
  - For each chart_type (bar, line, scatter, histogram, heatmap), construct a spec + df, call render, assert returns `go.Figure`.
- **Output:** `tests/test_renderer.py`.
- **Done when:** All 5 cases pass.

---

## Phase 7: Orchestrator

### T-060: Create pipeline.py
- **Action:** Write `src/csv_dashboard/orchestrator/pipeline.py`:
  ```python
  from dataclasses import dataclass, field
  import pandas as pd
  import plotly.graph_objects as go
  from pathlib import Path

  from csv_dashboard.ingestion.loader import load_csv, FileLoadError
  from csv_dashboard.quality.data_quality import run as run_quality
  from csv_dashboard.profiling.profiler import profile_dataframe
  from csv_dashboard.agents.chart_planner import plan_charts
  from csv_dashboard.agents.insight_writer import write_insights
  from csv_dashboard.charts.renderer import render as render_chart
  from csv_dashboard.charts.engine import generate_charts as fallback_charts
  from csv_dashboard.transparency.transparency import build as build_transparency
  from csv_dashboard.insights.chart_spec import ChartSpec
  from csv_dashboard.config import settings

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
      filename = Path(csv_path).name
      errors = []

      # Step 1: Ingestion
      con = load_csv(csv_path)

      # Step 2: Data quality → cleaned_data VIEW
      dq = run_quality(con)

      # Step 3: Profiling
      df = con.execute('SELECT * FROM "cleaned_data"').df()
      profile = profile_dataframe(df)
      profile["filename"] = filename

      # Step 4: Agent 1 — Chart Planner
      specs = plan_charts(profile, dq["llm_context"])

      # Step 5: Execute SQL for each spec
      chart_results: list[tuple[ChartSpec, pd.DataFrame]] = []
      charts: list[ChartArtifact] = []
      for spec in specs:
          try:
              result_df = con.execute(spec.sql_query).df()
              fig = render_chart(spec, result_df)
              charts.append(ChartArtifact(
                  title=spec.title, figure=fig, source="llm",
                  explanation=spec.plain_language_explanation,
              ))
              chart_results.append((spec, result_df))
          except Exception as e:
              errors.append(f"Chart '{spec.title}' failed: {e}")

      # Step 6: Fallback if too few LLM charts
      if len(charts) < 3:
          fallback = fallback_charts(df, filename)
          for fc in fallback:
              charts.append(ChartArtifact(
                  title=fc["title"], figure=fc["figure"], source="fallback",
              ))

      # Step 7: Agent 2 — Insight Writer (only on LLM charts)
      insights = write_insights(chart_results) if chart_results else []

      # Step 8: Transparency report
      transparency = build_transparency(dq["quality_report"])

      con.close()
      return PipelineResult(
          charts=charts, insights=insights,
          transparency=transparency, profile=profile,
          errors=errors,
      )
  ```
- **Output:** `src/csv_dashboard/orchestrator/pipeline.py`.
- **Done when:** Function returns valid PipelineResult.

### T-061: End-to-end test
- **Action:** Write `tests/test_pipeline_e2e.py`:
  - Use a synthetic 50-row CSV.
  - Mock both LLM calls.
  - Assert: ≥3 charts, ≥0 insights, transparency report exists.
  - Test with mocked LLM failure → assert fallback used.
- **Output:** `tests/test_pipeline_e2e.py`.
- **Done when:** Both scenarios pass.

---

## Phase 8: Streamlit UI

### T-070: Create app.py
- **Action:** Write `src/csv_dashboard/ui/app.py`:
  - Title and brief description.
  - `st.file_uploader` for CSV.
  - On upload, save to a temp file, call `pipeline.run`.
  - Show loading spinner with status updates.
  - Dataset summary card (rows × columns).
  - Transparency section (expander, collapsed).
  - Insights section (bulleted list).
  - Charts section (2-column grid).
  - Error banner if `result.errors` non-empty.
- **Output:** `src/csv_dashboard/ui/app.py`.
- **Done when:** `streamlit run src/csv_dashboard/ui/app.py` launches the UI.

### T-071: Add caching
- **Action:** Wrap `pipeline.run` in `@st.cache_data` keyed by file content hash:
  ```python
  @st.cache_data(show_spinner=False)
  def cached_run(file_bytes: bytes, filename: str) -> PipelineResult:
      with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
          tmp.write(file_bytes)
          tmp.flush()
          return pipeline.run(tmp.name)
  ```
- **Output:** Updated `ui/app.py`.
- **Done when:** Re-uploading the same file does not re-run the pipeline.

### T-072: Manual UX test
- **Action:** Run with both datasets:
  - Titanic → check 3+ charts, 3+ insights, transparency report.
  - NYC Airbnb → check same + ensure render in <30s.
- **Output:** Confirmation in a `MANUAL_TEST.md` log.
- **Done when:** Both datasets work end-to-end.

---

## Phase 9: Docker

### T-080: Write Dockerfile
- **Action:** Write `docker/Dockerfile`:
  ```Dockerfile
  FROM python:3.11-slim

  WORKDIR /app
  COPY pyproject.toml uv.lock ./
  RUN pip install uv && uv sync --frozen --no-dev

  COPY src ./src
  COPY .env ./.env

  EXPOSE 8501
  CMD ["uv", "run", "streamlit", "run", "src/csv_dashboard/ui/app.py",
       "--server.address=0.0.0.0", "--server.port=8501"]
  ```
- **Output:** `docker/Dockerfile`, `docker/.dockerignore`.
- **Done when:** `docker build -t csv-dashboard -f docker/Dockerfile .` succeeds.

### T-081: Test Docker run
- **Action:** `docker run -p 8501:8501 --env-file .env csv-dashboard`.
- **Output:** UI accessible at http://localhost:8501.
- **Done when:** Same dashboard as local works in browser.

---

## Phase 10: Documentation

### T-090: Write full README
- **Action:** Update `README.md`:
  - **What it does** (one paragraph).
  - **Architecture** (diagram + paragraph).
  - **Quick start** (uv setup, .env, run command).
  - **Docker** (build + run).
  - **Testing** (`pytest`).
  - **Project structure** (tree output).
  - **Trade-offs** (link to docs/TRADE_OFFS.md).
  - **What's missing** (link to docs/PRODUCTION_NOTES.md).
- **Output:** Final `README.md`.
- **Done when:** A new developer can run the project from the README alone.

### T-091: Write ARCHITECTURE.md
- **Action:** `docs/ARCHITECTURE.md` — deep dive:
  - The 8-step pipeline (with diagram).
  - Why DuckDB.
  - Why two agents.
  - The fallback engine.
  - Module contracts.
- **Output:** `docs/ARCHITECTURE.md`.

### T-092: Write TRADE_OFFS.md
- **Action:** `docs/TRADE_OFFS.md`:
  - What we cut and why.
  - What we rejected and why.
  - What we'd add with another month.
- **Output:** `docs/TRADE_OFFS.md`.

### T-093: Write PRODUCTION_NOTES.md
- **Action:** `docs/PRODUCTION_NOTES.md`:
  - Cost analysis per CSV.
  - Latency analysis.
  - Failure modes and recovery.
  - Security considerations.
  - Observability.
  - Scaling path.
- **Output:** `docs/PRODUCTION_NOTES.md`.

---

## Phase 11: CI

### T-100: GitHub Actions workflow
- **Action:** Write `.github/workflows/ci.yml`:
  ```yaml
  name: CI
  on: [push, pull_request]
  jobs:
    test:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v3
        - run: uv sync
        - run: uv run ruff check .
        - run: uv run pytest --cov=src
  ```
- **Output:** `.github/workflows/ci.yml`.
- **Done when:** PRs trigger the workflow; tests pass with mocked LLM.

---

## Phase 12: Presentation

### T-110: Slide outline
- **Action:** Create `docs/PRESENTATION.md` (or `.pptx`) with 5-10 slides as listed in `PROJECT_CONTEXT.md` Section 9.
- **Output:** Slide deck.
- **Done when:** Each slide has clear content; rehearsal ≤10 minutes.

### T-111: Rehearse demo
- **Action:** Practice the live walkthrough on both datasets.
- **Output:** Confidence in the flow.
- **Done when:** Demo completes in ≤5 minutes with no surprises.

---

## Summary checklist

When everything below is checked, the MVP is done:

- [ ] All Phase 1 tasks (foundation)
- [ ] All Phase 2 tasks (move existing modules)
- [ ] All Phase 3 tasks (ingestion)
- [ ] All Phase 4 tasks (LLM client)
- [ ] All Phase 5 tasks (prompts + agents)
- [ ] All Phase 6 tasks (renderer)
- [ ] All Phase 7 tasks (orchestrator)
- [ ] All Phase 8 tasks (Streamlit UI)
- [ ] All Phase 9 tasks (Docker)
- [ ] All Phase 10 tasks (documentation)
- [ ] All Phase 11 tasks (CI)
- [ ] All Phase 12 tasks (presentation)
- [ ] **Acceptance criteria** from `spec.md` Section 7 verified.

---

**End of Tasks. Version 1.0. Date: 2026-05-19.**
