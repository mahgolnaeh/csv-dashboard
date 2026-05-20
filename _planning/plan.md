# Plan: CSV Dashboard MVP

> How we build what's specified in `spec.md`.
> Tech stack, architecture, and implementation phases.

---

## 1. Technology Stack

### Runtime

| Layer | Choice | Version |
|---|---|---|
| Language | Python | 3.11+ |
| Package manager | uv | latest |
| Build config | pyproject.toml | PEP 621 |

### Core libraries

| Purpose | Library | Why |
|---|---|---|
| Data engine | duckdb | Single source of truth, fast on 48k rows |
| DataFrames | pandas 2.x | Profile-time only; not in hot path |
| Numerics | numpy | Statistical computations |
| Validation | pydantic v2 | Type + cross-field validation |
| Config | pydantic-settings | Typed .env loading |
| LLM | httpx | Direct calls to OpenRouter — no SDK |
| Charts | plotly | Interactive, professional |
| Stats | scipy | Outlier detection, correlations |
| UI | streamlit | Fast MVP |
| Env | python-dotenv | .env loading (via pydantic-settings) |
| Logging | structlog | Structured JSON logs |

### Dev libraries

| Purpose | Library |
|---|---|
| Testing | pytest, pytest-mock |
| Linting | ruff |
| Type checking | mypy (optional) |
| Coverage | pytest-cov |

### Infrastructure

| Purpose | Choice |
|---|---|
| Container | Docker |
| CI | GitHub Actions |
| Version control | Git |

### LLM provider

- **OpenRouter** as the gateway.
- Default model: `anthropic/claude-haiku-4.5` for both agents.
- Alternative models tested: `openai/gpt-4o-mini`, `google/gemini-flash-1.5`.
- Configurable via `.env` — no code change to switch models.

---

## 2. Folder Structure

```
csv-dashboard/
├── .specify/                              ← spec-kit artifacts
│   ├── memory/constitution.md
│   └── specs/001-csv-dashboard/
│       ├── spec.md
│       ├── plan.md
│       └── tasks.md
│
├── src/csv_dashboard/
│   ├── __init__.py
│   ├── config.py                          ← settings + env loading
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   └── loader.py                      ← DuckDB CSV loader
│   │
│   ├── quality/
│   │   ├── __init__.py
│   │   └── data_quality.py                ← VIEW builder (existing)
│   │
│   ├── profiling/
│   │   ├── __init__.py
│   │   └── profiler.py                    ← profile_dataframe (existing)
│   │
│   ├── insights/
│   │   ├── __init__.py
│   │   ├── llm_client.py                  ← OpenRouter HTTP client
│   │   ├── chart_spec.py                  ← Pydantic models (existing)
│   │   └── prompts.py                     ← system prompts + builders
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── chart_planner.py               ← Agent 1
│   │   └── insight_writer.py              ← Agent 2 (new)
│   │
│   ├── charts/
│   │   ├── __init__.py
│   │   ├── engine.py                      ← fallback rules (existing)
│   │   └── renderer.py                    ← Plotly figure builder
│   │
│   ├── transparency/
│   │   ├── __init__.py
│   │   └── transparency.py                ← plain-English report (existing)
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   └── pipeline.py                    ← wires all modules
│   │
│   └── ui/
│       ├── __init__.py
│       └── app.py                         ← Streamlit UI
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                        ← shared fixtures
│   ├── test_data_quality.py
│   ├── test_profiler.py
│   ├── test_chart_spec.py
│   ├── test_chart_planner.py              ← LLM mocked
│   ├── test_insight_writer.py             ← LLM mocked
│   ├── test_pipeline_e2e.py               ← full flow, LLM mocked
│   └── fixtures/
│       ├── titanic_sample.csv             ← 50 rows
│       └── airbnb_sample.csv              ← 100 rows
│
├── docker/
│   ├── Dockerfile
│   └── .dockerignore
│
├── .github/workflows/
│   └── ci.yml                             ← lint + test on PR
│
├── docs/
│   ├── ARCHITECTURE.md                    ← deep dive for presentation
│   ├── TRADE_OFFS.md                      ← what was cut
│   └── PRODUCTION_NOTES.md                ← scalability, cost, failures
│
├── .env.example                           ← OPENROUTER_API_KEY=
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## 3. Module Contracts

Each module exposes exactly one public function. Internal helpers are
underscore-prefixed. No module imports from another module's internals.

### 3.1 `ingestion/loader.py`

```python
def load_csv(path: str) -> duckdb.DuckDBPyConnection:
    """Load CSV into DuckDB. Raises FileLoadError on failure."""
```

### 3.2 `quality/data_quality.py`

```python
def run(con: duckdb.DuckDBPyConnection, raw_table: str = "raw_data") -> QualityResult:
    """
    Returns QualityResult with:
      view_name, quality_report, dropped_cols, clean_columns,
      llm_context, has_issues
    """
```

### 3.3 `profiling/profiler.py`

```python
def profile_dataframe(df: pd.DataFrame) -> dict:
    """Returns structured profile dict."""
```

### 3.4 `insights/llm_client.py`

```python
def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int = 2048,
) -> str:
    """Returns assistant message text. Raises LLMError on failure."""
```

### 3.5 `insights/chart_spec.py`

```python
class ChartSpec(BaseModel): ...
class ChartSpecList(BaseModel): ...
```

### 3.6 `insights/prompts.py`

```python
CHART_PLANNER_SYSTEM: str
INSIGHT_WRITER_SYSTEM: str

def build_planner_prompt(profile: dict, quality_context: str) -> str: ...
def build_planner_retry_prompt(original: str, error: str, columns: list[str]) -> str: ...
def build_insight_prompt(chart_results: list[tuple]) -> str: ...
```

### 3.7 `agents/chart_planner.py`

```python
def plan_charts(profile: dict, quality_context: str) -> list[ChartSpec]:
    """Returns 3-5 validated specs. Empty list on full failure."""
```

### 3.8 `agents/insight_writer.py`

```python
def write_insights(
    chart_results: list[tuple[ChartSpec, pd.DataFrame]],
) -> list[str]:
    """Returns 3-5 plain-English insights. Empty list on full failure."""
```

### 3.9 `charts/engine.py`

```python
def generate_charts(df: pd.DataFrame, filename: str = "") -> list[dict]:
    """Returns [{'title', 'figure', 'rule'}, ...] using R00-R12."""
```

### 3.10 `charts/renderer.py`

```python
def render(spec: ChartSpec, df: pd.DataFrame) -> go.Figure:
    """Render a single chart spec + query result as a Plotly figure."""
```

### 3.11 `transparency/transparency.py`

```python
def build(quality_report: list[dict]) -> dict:
    """Returns {has_changes, sentences, plain_text}."""

def show_in_streamlit(quality_report: list[dict]) -> None:
    """Render the report directly in Streamlit."""
```

### 3.12 `orchestrator/pipeline.py`

```python
@dataclass
class PipelineResult:
    charts: list[ChartArtifact]
    insights: list[str]
    transparency: dict
    profile: dict
    errors: list[str]

def run(csv_path: str, verbose: bool = False) -> PipelineResult:
    """The single entry point for the system."""
```

### 3.13 `ui/app.py`

Streamlit script — no exposed functions. Run with `streamlit run`.

---

## 4. Data Flow

```
CSV file
   │
   ▼
[loader.load_csv]
   │ con (DuckDB) with raw_data table
   ▼
[data_quality.run]
   │ con now also has cleaned_data VIEW
   │ quality_result (report, llm_context)
   ▼
[con.execute("SELECT * FROM cleaned_data").df()]
   │ pd.DataFrame
   ▼
[profiler.profile_dataframe]
   │ profile dict
   ▼
[chart_planner.plan_charts]
   │ list[ChartSpec]   (Agent 1: LLM call + Pydantic validation + retry)
   ▼
[for each spec:]
   │ [Pydantic SQL validators]
   │ [con.execute(spec.sql_query).df()]   (retry once on SQL error)
   │ result_df
   ▼
list[(spec, result_df)]
   │
   ▼
[insight_writer.write_insights]   ← (Agent 2: LLM call)
   │ list[str] insights
   ▼
[renderer.render] for each (spec, result_df)
   │ list[plotly.Figure]
   ▼
[transparency.build]
   │ transparency report
   ▼
PipelineResult(charts, insights, transparency, profile, errors)
   │
   ▼
[ui.app] renders everything in Streamlit
```

If `chart_planner` returns < 3 specs:
```
[charts.engine.generate_charts(df, filename)]
   │ fallback charts (deterministic)
   ▼
   merged into final result
```

---

## 5. Error Handling Strategy

| Failure | Recovery |
|---|---|
| CSV unreadable | Surface clear error to user, do not crash |
| All columns dropped by data_quality | Use fallback engine, skip LLM |
| LLM returns bad JSON | Retry once with error in prompt |
| LLM returns spec failing Pydantic | Retry once with error in prompt |
| Specific SQL fails | Retry once with error + column list |
| Multiple specs fail | Use fallback engine to fill the gap |
| OpenRouter unreachable | Use fallback engine entirely |
| OpenRouter rate-limited | Use fallback engine entirely |
| Plotly render fails | Skip that chart, log warning |

The user always sees something. They might see a "simplified analysis" badge,
but the dashboard always renders.

---

## 6. Implementation Phases

### Phase 1: Foundation (Day 1)

**Goal:** Working folder structure, dependencies installed, `.env` template ready.

Tasks:
- T-001: `uv init csv-dashboard`, create `pyproject.toml` with all dependencies.
- T-002: Create folder structure as in Section 2.
- T-003: Create `config.py` with `Settings` class.
- T-004: Create `.env.example` and `.gitignore`.
- T-005: Initial `README.md` with project description.

**Done when:** `uv run python -c "from csv_dashboard.config import settings; print(settings)"` works.

### Phase 2: Move existing modules (Day 1)

**Goal:** Move the 5 existing modules into the new structure without changes.

Tasks:
- T-010: Copy `chart_engine.py` → `src/csv_dashboard/charts/engine.py`.
- T-011: Copy `data_quality.py` → `src/csv_dashboard/quality/data_quality.py`.
- T-012: Copy `profiler.py` → `src/csv_dashboard/profiling/profiler.py`.
- T-013: Copy `chart_spec.py` → `src/csv_dashboard/insights/chart_spec.py`.
- T-014: Copy `transparency.py` → `src/csv_dashboard/transparency/transparency.py`.
- T-015: Add `__init__.py` files exporting public functions.
- T-016: Smoke-test imports.

**Done when:** All modules importable, existing test logic still passes.

### Phase 3: OpenRouter LLM client (Day 2)

**Goal:** Replace Anthropic SDK with OpenRouter via httpx.

Tasks:
- T-020: Create `insights/llm_client.py` with `call_llm(...)`.
- T-021: Define `LLMError` exception.
- T-022: Add retry-on-network-error logic (exponential backoff, max 3 tries).
- T-023: Unit tests with mocked httpx.
- T-024: Manual test with real OpenRouter key (one-off, not in CI).

**Done when:** `call_llm` works with Haiku, GPT-4o-mini, and Gemini Flash.

### Phase 4: Agentic layer (Day 2-3)

**Goal:** Two-agent system: Chart Planner + Insight Writer.

Tasks:
- T-030: Create `insights/prompts.py` with system prompts + builders.
- T-031: Create `agents/chart_planner.py`:
  - Call LLM with planner prompt.
  - Parse JSON, validate with `ChartSpecList`.
  - Retry once on failure.
- T-032: Create `agents/insight_writer.py`:
  - Summarize result_df contents (top values, ranges).
  - Call LLM with writer prompt.
  - Parse and return list of insight sentences.
- T-033: Unit tests for both agents with mocked LLM.

**Done when:** Both agents produce valid output for the Titanic test fixture.

### Phase 5: Renderer + orchestrator (Day 3)

**Goal:** Wire everything together.

Tasks:
- T-040: Extract `_render` from old pipeline → `charts/renderer.py`.
- T-041: Build `orchestrator/pipeline.py`:
  - Compose: loader → data_quality → profiler → chart_planner → execute → insight_writer → renderer.
  - Handle SQL retry per spec.
  - Fall back to `charts.engine` if planner produces <3 specs.
- T-042: End-to-end test with synthetic CSV + mocked LLM.

**Done when:** `pipeline.run("tests/fixtures/titanic_sample.csv")` returns a complete `PipelineResult`.

### Phase 6: Streamlit UI (Day 3-4)

**Goal:** User-facing app.

Tasks:
- T-050: Build `ui/app.py`:
  - Upload widget.
  - Loading spinner with status updates.
  - Dataset summary card.
  - Transparency expander.
  - Insights bulleted list.
  - Charts grid (2 columns).
  - Error banner for fatal failures.
- T-051: Cache `pipeline.run` per file hash with `@st.cache_data`.
- T-052: Manual UX testing with Titanic and Airbnb.

**Done when:** Both datasets produce a working dashboard in the browser.

### Phase 7: Docker + Docs (Day 4)

**Goal:** Shippable artifact.

Tasks:
- T-060: Write `docker/Dockerfile` based on `python:3.11-slim`.
- T-061: Write `.dockerignore`.
- T-062: Test `docker build` and `docker run` locally.
- T-063: Update `README.md`:
  - What it does.
  - How to run locally (`uv run streamlit run ...`).
  - How to run in Docker.
  - How to test.
  - What's missing.
- T-064: Write `docs/ARCHITECTURE.md` (deep dive for presentation).
- T-065: Write `docs/TRADE_OFFS.md` (what was cut, why).
- T-066: Write `docs/PRODUCTION_NOTES.md` (scale, cost, failure modes).

**Done when:** `docker run -p 8501:8501 csv-dashboard` shows the UI.

### Phase 8: CI + presentation (Day 5)

**Goal:** Polish and final deliverables.

Tasks:
- T-070: Write `.github/workflows/ci.yml`:
  - Lint with ruff.
  - Run pytest with mocked LLM.
- T-071: Write 5–10 slide presentation (markdown or pptx).
- T-072: Rehearse the live walkthrough.

**Done when:** Repo passes CI, presentation is rehearsed.

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenRouter API down during demo | Low | High | Fallback engine always works |
| LLM produces creative-but-wrong SQL | Medium | Medium | Pydantic + SQL validators + retry |
| 48k-row file is slow to render | Medium | Medium | Streamlit cache; profile uses DuckDB not pandas |
| Streamlit reruns on every interaction | High | Low | `@st.cache_data` on the pipeline |
| Demo CSV is weird in unexpected ways | Medium | Medium | Fallback engine handles any structure |
| Time runs out before docs are done | Medium | High | Write docs as we go, not at the end |

---

## 8. Definition of Done (per phase)

A phase is done when:
1. All tasks in the phase are checked off.
2. Tests for that phase pass.
3. The "Done when" condition for that phase is verified.
4. The code is committed to a feature branch.
5. The relevant README section is updated.

The whole project is done when **Section 7 of `spec.md` (acceptance criteria)** is satisfied.

---

**End of Plan. Version 1.0. Date: 2026-05-19.**
