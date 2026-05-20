# PROJECT_CONTEXT.md

> **Purpose of this document:** Complete project context, design decisions, and rationale.
> This is the **ground truth** for the implementation session that follows.
> Read this fully before writing any code.

---

## 1. Context: Why this project exists

This is an **MVP for a Deutsche Telekom AI & Digital Innovation internship case study**.
Deadline: 19 May 2026. The case study is high-stakes for the candidate (Mahgol).

### What Telekom asked for

Build an MVP that turns **any CSV** into a **dashboard with insights**, for a
**non-technical user**. The user uploads a CSV — the system must work without
knowing the schema in advance, across different domains, data types, and dataset
sizes (hundreds to tens of thousands of rows).

**Input:** any CSV file.
**Output:** a dashboard + written insights.

### Test datasets (must work on both)

- **Small (Titanic):** ~891 rows, mixed types, missing values
  `https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv`
- **Large (NYC Airbnb 2019):** ~48,895 rows, 16 columns, dates & geo
  `https://raw.githubusercontent.com/erkansirin78/datasets/master/AB_NYC_2019.csv`

### Deliverables

1. Source code repo + clear README
2. 5–10 slide presentation
3. Live demo call

### How Telekom evaluates (equal weight)

- Problem framing (business, not technical)
- System design (handles unknown schemas, growing data)
- Tech choices (why these, what was rejected)
- Production thinking (scalability, cost, performance, failure modes, observability)
- Trade-offs & limitations
- UX (would a non-technical user actually use it)
- Communication (written and live)

### Job-description signals (what this internship looks for)

- AI Agents & Automation (agentic AI experience required)
- Data Analytics & Dashboards
- At least one orchestration framework familiarity (LangGraph, LangChain, Claude SDK, etc.)
- Software engineering fundamentals (Git, CI/CD, containerization, clean code)
- Full-stack development (backend + frontend + production)
- Database knowledge (SQL/NoSQL)
- Cloud (nice-to-have)

---

## 2. Architecture: The 8-step pipeline

```
[1] CSV upload
       ↓
[2] DuckDB loads raw CSV          → table: raw_data
       ↓
[3] data_quality.py               → reads raw_data, builds VIEW: cleaned_data
       ↓
[4] profiler.py                   → reads cleaned_data, returns profile dict
       ↓
[5] AGENT 1: Chart Planner (LLM)  → returns 3-5 chart specs (JSON)
       ↓
[6] Pydantic + SQL validation     → blocks bad specs; retry LLM once on error
       ↓
[7] DuckDB executes spec.sql_query on cleaned_data
       ↓
[8] AGENT 2: Insight Writer (LLM) → reads query results, writes plain insights
       ↓
[9] Plotly renders charts + Streamlit shows everything
       ↓
   (Fallback at any step: chart_engine.py — deterministic rules, always works)
```

### Why DuckDB is the single source of truth

- One data layer (no pandas/DuckDB mismatch)
- SQL-native cleanup: `TRIM`, `TRY_CAST`, `CASE WHEN ... THEN NULL`, etc.
- Fast on large files (48k+ rows)
- The cleaned VIEW is a transformation layer — raw data is preserved

### Why two agents, not one big prompt

- **Agent 1 (Chart Planner)** works from the *profile* — aggregated stats only.
  Decides what charts to make and writes SQL.
- **Agent 2 (Insight Writer)** works from the *actual query results* — real data
  after execution. Writes 3–5 short, plain-language insights for non-technical users.
- This is genuinely agentic: two LLM steps with explicit responsibilities, DuckDB
  as the tool used between them. It is defensible in the presentation as a
  minimal multi-agent design without over-engineering with LangGraph.

### Why a fallback engine

- LLM calls can fail (network, rate limits, bad JSON, hallucinated columns).
- chart_engine.py is deterministic — rule-based (R01–R12). Always works.
- Triggered when: LLM JSON fails Pydantic after retry, or SQL fails after retry,
  or fewer than 3 LLM charts produced.
- Tells the interviewer: "we thought about failure modes."

---

## 3. Key design decisions (the trade-offs Telekom asks about)

| Decision | What we chose | Why | What we rejected |
|---|---|---|---|
| Data layer | DuckDB | SQL-native, fast on 48k rows, in-process (no server), free | Pandas-only (slower, two paths); SQLite (slower for analytics) |
| LLM provider | OpenRouter | One API, multiple models (Claude Haiku, GPT-4o-mini, Gemini Flash), easy to swap, cost-flexible | Anthropic SDK directly (vendor lock-in); LangChain (too heavy for 2 LLM calls) |
| Validation | Pydantic | Type + value + cross-field validation in one place | Manual JSON checks (error-prone); JSON Schema (less Pythonic) |
| UI | Streamlit | Fast MVP, non-technical users can run it, good for charts | Gradio (less flexible for dashboards); FastAPI + HTML (too much work for MVP) |
| Agentic | Custom 2-agent orchestrator | Real value (Chart Planner + Insight Writer); no framework overhead | LangGraph (overkill for 2 agents); single big prompt (no real agentic structure) |
| Fallback | Deterministic rule engine | Always works, zero cost, zero latency | LLM retry with different prompts (more failures, more cost) |
| Deployment | Dockerfile (local run) | Reproducible, easy to demo | Cloud deploy (out of scope for MVP) |

---

## 4. Module-by-module design

### 4.1 `ingestion/loader.py`

**Role:** load a CSV into DuckDB as `raw_data` table.

**Input:** csv path
**Output:** open DuckDB connection with `raw_data` registered

**Logic:**
```python
con = duckdb.connect()
con.execute(f"CREATE OR REPLACE TABLE raw_data AS "
            f"SELECT * FROM read_csv_auto('{path}', header=true)")
return con
```

Edge cases handled: unreadable file → `RuntimeError` with clear message.

### 4.2 `quality/data_quality.py`

**Role:** detect data issues, auto-fix safe ones, build `cleaned_data` VIEW.

**Input:** DuckDB connection, raw_table name
**Output:** dict with `view_name`, `quality_report`, `dropped_cols`, `clean_columns`, `llm_context`, `has_issues`

**Severity levels:**
- `info` — auto-fixed silently (whitespace, sentinel nulls, currency symbols, numeric strings, datetime strings)
- `warn` — detected, reported, **not changed** (outliers, mixed types, inconsistent dates, duplicate rows, high missingness)
- `drop` — column removed from VIEW SELECT (all-null, constant, duplicate columns)

**Key principle:** any fix is a SQL expression in the VIEW. Raw data is never mutated.

**Examples of SQL fixes built into the VIEW:**
- `"$100"` → `TRY_CAST(regexp_replace(col, '[€$£¥₹,\\s]', '', 'g') AS DOUBLE)`
- `"N/A"` → `CASE WHEN LOWER(TRIM(col)) IN ('n/a',...) THEN NULL ELSE col END`
- `"2024-01-01"` → `TRY_CAST(TRIM(col) AS TIMESTAMP)`

### 4.3 `profiling/profiler.py`

**Role:** profile `cleaned_data` view, return a compact dict for the LLM.

**Input:** pd.DataFrame (from `SELECT * FROM cleaned_data`)
**Output:** dict with row_count, column_count, semantic_type_summary, columns (with stats), warnings

**Semantic types detected:** `numeric`, `categorical`, `datetime`, `boolean`, `identifier`, `text`

**For numeric columns includes:** min, max, mean, median, std, q1, q3, **skewness**, **outlier_count_iqr**

**Output size:** ~1000 tokens — fits comfortably in any LLM context.

### 4.4 `insights/llm_client.py` (NEW for OpenRouter)

**Role:** unified LLM call interface using OpenRouter.

```python
def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = "anthropic/claude-haiku-4.5",
    max_tokens: int = 2048,
) -> str:
    # POST to https://openrouter.ai/api/v1/chat/completions
    # Header: Authorization: Bearer {OPENROUTER_API_KEY}
    # Returns the assistant message content as string
```

Read API key from `.env` (via `python-dotenv`). Never log the key.

### 4.5 `insights/chart_spec.py`

**Role:** Pydantic model for chart specs returned by LLM.

**Fields (full schema):**
- `title` (3–80 chars)
- `chart_type` (Literal: bar | line | scatter | histogram | heatmap)
- `business_question` (10–200 chars)
- `sql_query` (must start with SELECT, must reference `cleaned_data`, no DROP/INSERT/UPDATE/DELETE)
- `x_column`, `y_column`, `color_column` (with cross-field rules)
- `aggregation` (Literal: COUNT | AVG | SUM | MEDIAN | MIN | MAX | NONE)
- `sort_order` (Literal: asc | desc | none)
- `limit` (2–50)
- `x_label`, `y_label` (≤60 chars, human-readable)
- `plain_language_explanation` (20–300 chars)

**Cross-field validators:**
- histogram must have `y_column=None`
- scatter must have both `x_column` and `y_column`
- heatmap must have both as `None`
- bar/line must not have `aggregation=NONE`
- line must have `sort_order=none` (chronological order from datetime)

**Wrapper:** `ChartSpecList(charts: list[ChartSpec])` with min_length=3, max_length=5.

### 4.6 `insights/prompts.py` (NEW — extracted from pipeline)

Contains:
- `CHART_PLANNER_SYSTEM_PROMPT` — instructs LLM about the JSON schema, rules, semantic types to avoid (identifier, text), and that the table is `cleaned_data`.
- `INSIGHT_WRITER_SYSTEM_PROMPT` — instructs LLM to write 3-5 plain-English insights from query results. No jargon. Short sentences.
- `build_planner_prompt(profile, quality_context)` — formats the dataset context for Agent 1.
- `build_insight_prompt(chart_results)` — formats actual query results for Agent 2.

### 4.7 `agents/chart_planner.py` (NEW)

**Role:** LLM-based agent that generates chart specs.

**Logic:**
```python
def plan_charts(profile: dict, quality_context: str) -> list[ChartSpec]:
    prompt = build_planner_prompt(profile, quality_context)
    for attempt in range(MAX_RETRIES + 1):
        raw = call_llm(CHART_PLANNER_SYSTEM_PROMPT, prompt)
        try:
            return ChartSpecList(**json.loads(raw)).charts
        except (ValidationError, JSONDecodeError) as e:
            prompt = build_retry_prompt(prompt, str(e))
    return []  # caller will use fallback
```

### 4.8 `agents/insight_writer.py` (NEW)

**Role:** LLM-based agent that writes plain-language insights from chart results.

**Input:** list of `(spec, result_df)` tuples — what was asked + actual data.
**Output:** list of short insight strings.

**Logic:**
```python
def write_insights(chart_results: list[tuple[ChartSpec, pd.DataFrame]]) -> list[str]:
    # Summarize each result_df: top values, ranges, key numbers
    # Send to LLM with INSIGHT_WRITER_SYSTEM_PROMPT
    # Return list of plain sentences
```

Insights look like: `"Manhattan listings cost 3× more than Brooklyn on average."`

### 4.9 `charts/engine.py` (renamed from chart_engine.py)

**Role:** deterministic fallback. Rule-based (R00–R12). No LLM.

Rules (already implemented):
- R00: summary card
- R01: numeric → histogram
- R02: numeric with outliers → histogram + outlier markers (NOT boxplot)
- R03: low/medium-cardinality categorical → bar of counts
- R04: numeric + categorical → bar of mean/median by category
- R05: scatter only if |r| > 0.4, with trend line
- R06: heatmap, only |r| > 0.5 shown
- R07: datetime → records over time
- R08: datetime + numeric → average over time
- R09: skip identifier columns
- R10: skip columns >40% missing
- R11: top-N for high-cardinality categoricals
- R12: missingness bar chart

### 4.10 `charts/renderer.py` (NEW — extracted from pipeline)

**Role:** turn `(ChartSpec, result_df)` into a `plotly.graph_objects.Figure`.

Uses `chart_type` to dispatch to bar/line/scatter/histogram/heatmap renderers.
Applies `x_label`, `y_label`, `sort_order`, `color_column`, `limit`.
Adds `plain_language_explanation` as a subtitle annotation.

### 4.11 `transparency/transparency.py`

**Role:** turn `quality_report` into plain-English sentences for the user.

**English only, no Persian in code.**

Output example:
```
While preparing your data, the following changes were made:
  - Column "empty": No data found. Removed from analysis.
  - Column "price": Currency symbols removed. Values converted to numbers.
  - Column "score": 1 value(s) are unusually high or low. Shown as-is in charts.
```

Has a `show_in_streamlit()` helper for direct use in the UI.

### 4.12 `orchestrator/pipeline.py`

**Role:** wires all modules. The single entry point.

```python
def run(csv_path: str) -> PipelineResult:
    # 1. ingestion.loader.load(csv_path) → con
    # 2. quality.data_quality.run(con) → dq
    # 3. profiling.profiler.profile_dataframe(df) → profile
    # 4. agents.chart_planner.plan_charts(profile, dq.llm_context) → specs
    # 5. for each spec: validate → execute → collect
    #    (retry once on SQL fail, fallback to engine for failures)
    # 6. agents.insight_writer.write_insights(chart_results) → insights
    # 7. transparency.build(dq.quality_report) → transparency_report
    # Return: PipelineResult(charts, insights, transparency_report)
```

### 4.13 `ui/app.py` (Streamlit)

**Layout:**
```
┌─────────────────────────────────────────────────┐
│  CSV Dashboard                                  │
│                                                 │
│  [Upload CSV]                                   │
│                                                 │
│  ── Dataset summary ──                          │
│  N rows × M columns                             │
│                                                 │
│  ── Data preparation report ──   [expander]     │
│  - Column "X": ... fixed                        │
│  - Column "Y": ... warning                      │
│                                                 │
│  ── Key insights ──                             │
│  • Manhattan listings cost 3× more on average.  │
│  • Reviews drop sharply after 30 days.          │
│  • ...                                          │
│                                                 │
│  ── Charts ──                                   │
│  [chart 1]  [chart 2]                           │
│  [chart 3]  [chart 4]                           │
└─────────────────────────────────────────────────┘
```

Handles loading spinner, errors, and the file size warning for large files.

### 4.14 `config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openrouter_api_key: str
    chart_planner_model: str = "anthropic/claude-haiku-4.5"
    insight_writer_model: str = "anthropic/claude-haiku-4.5"
    max_llm_retries: int = 1
    top_n_categories: int = 10
    missing_threshold: float = 0.40
    correlation_threshold: float = 0.40
    heatmap_threshold: float = 0.50

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 5. Final folder structure

```
csv-dashboard/
├── .specify/                          ← spec-kit artifacts
│   ├── memory/
│   │   └── constitution.md
│   └── specs/001-csv-dashboard/
│       ├── spec.md
│       ├── plan.md
│       └── tasks.md
│
├── src/csv_dashboard/
│   ├── __init__.py
│   ├── config.py
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   └── loader.py
│   │
│   ├── quality/
│   │   ├── __init__.py
│   │   └── data_quality.py
│   │
│   ├── profiling/
│   │   ├── __init__.py
│   │   └── profiler.py
│   │
│   ├── insights/
│   │   ├── __init__.py
│   │   ├── llm_client.py
│   │   ├── chart_spec.py
│   │   └── prompts.py
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── chart_planner.py
│   │   └── insight_writer.py
│   │
│   ├── charts/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   └── renderer.py
│   │
│   ├── transparency/
│   │   ├── __init__.py
│   │   └── transparency.py
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   └── pipeline.py
│   │
│   └── ui/
│       ├── __init__.py
│       └── app.py
│
├── tests/
│   ├── __init__.py
│   ├── test_data_quality.py
│   ├── test_profiler.py
│   ├── test_chart_spec.py
│   ├── test_chart_planner.py        ← with LLM mocks
│   ├── test_pipeline_e2e.py         ← full flow with synthetic CSV
│   └── fixtures/
│       └── sample.csv
│
├── docker/
│   ├── Dockerfile
│   └── .dockerignore
│
├── .github/workflows/
│   └── ci.yml
│
├── docs/
│   ├── ARCHITECTURE.md              ← deep dive for the presentation
│   ├── TRADE_OFFS.md                ← what was cut and why
│   └── PRODUCTION_NOTES.md          ← scalability, cost, failure modes
│
├── .env.example
├── .gitignore
├── pyproject.toml                   ← uv-based
├── README.md
└── PROJECT_CONTEXT.md               ← this file
```

---

## 6. Existing code (already written, needs to be moved into the new structure)

The current session produced these files (in `/mnt/user-data/outputs/`):

1. **`chart_engine.py`** (576 lines) — deterministic R01–R12 rule engine. Goes to `src/csv_dashboard/charts/engine.py` unchanged.

2. **`data_quality.py`** (335 lines) — DuckDB-first quality module. Goes to `src/csv_dashboard/quality/data_quality.py` unchanged.

3. **`profiler.py`** (215 lines) — hybrid profiler. Goes to `src/csv_dashboard/profiling/profiler.py` unchanged.

4. **`chart_spec.py`** (290 lines) — Pydantic models. Goes to `src/csv_dashboard/insights/chart_spec.py` unchanged.

5. **`transparency.py`** (175 lines) — user-facing transparency report. Goes to `src/csv_dashboard/transparency/transparency.py` unchanged.

6. **`pipeline.py`** (450 lines) — current monolithic orchestrator. Must be **broken apart** into:
   - `agents/chart_planner.py` (LLM call + retry logic)
   - `agents/insight_writer.py` (NEW — does not exist yet)
   - `insights/llm_client.py` (NEW — OpenRouter client)
   - `insights/prompts.py` (NEW — system prompts + builders)
   - `charts/renderer.py` (the `_render()` function)
   - `orchestrator/pipeline.py` (thin orchestrator that calls the modules)

---

## 7. What is genuinely new (must be written from scratch)

| File | Why new |
|---|---|
| `insights/llm_client.py` | OpenRouter replaces Anthropic SDK |
| `insights/prompts.py` | Extract system prompts; add Insight Writer prompts |
| `agents/chart_planner.py` | Wrap LLM call + retry into agent module |
| `agents/insight_writer.py` | Brand new — generates plain-English insights |
| `charts/renderer.py` | Extract `_render()` from pipeline.py |
| `orchestrator/pipeline.py` | Thin wiring layer |
| `ui/app.py` | Streamlit UI |
| `config.py` | pydantic-settings with .env loading |
| `tests/*` | Unit + integration tests |
| `docker/Dockerfile` | Containerization |
| `.github/workflows/ci.yml` | CI pipeline |
| `docs/*` | Architecture, trade-offs, production notes |

---

## 8. Things that are easy to forget

1. **The table name in SQL is `cleaned_data`, not `data`.** Both `chart_spec.py` validators and the system prompts reference `cleaned_data`.

2. **The fallback engine works on `df` (pandas), not the DuckDB view directly.** When falling back, materialize: `df = con.execute('SELECT * FROM cleaned_data').df()`, then call `chart_engine.generate_charts(df, filename)`.

3. **Insight Writer needs query results, not just specs.** After Step 7 (DuckDB executes), pass `(spec, result_df)` pairs to Agent 2.

4. **OpenRouter key from `.env` only.** Never hard-code, never log.

5. **No Persian text in any code file or comment.** UI labels and messages all in English.

6. **Streamlit reruns on every interaction.** Cache the heavy computation: `@st.cache_data` on `pipeline.run(csv_path)` keyed by file hash.

7. **Large CSVs (NYC Airbnb, 48k rows):** test that profiling and chart rendering stay <30s. If not, sample 10k rows for chart rendering only (profiling still uses full data via DuckDB).

8. **Pydantic v2 syntax.** Use `model_validator(mode="after")` and `field_validator` decorators, not v1's `@validator`.

9. **`pandas 2.x` quirks:** `is_string_dtype()` returns True for the new string dtype, but `dtype == object` does NOT. The existing code uses `pd.api.types.is_string_dtype()` correctly — keep that pattern.

10. **DuckDB date parsing**: `pd.to_datetime(..., infer_datetime_format=True)` is removed in pandas 2.x. The existing code uses `pd.to_datetime(..., errors="coerce")` correctly.

---

## 9. Things to mention in the presentation (5–10 slides)

**Slide 1: The problem (business framing)**
A non-technical user has a CSV. They want to understand it without writing code.
The system must handle unknown schemas, dirty data, and growing data sizes.

**Slide 2: Architecture overview**
The 8-step pipeline diagram. Highlight DuckDB as single source of truth.

**Slide 3: Why DuckDB**
Fast on 48k rows, SQL-native cleanup, in-process (no server), free.
Rejected: pandas-only (slower), SQLite (slower for analytics).

**Slide 4: The agentic layer**
Two agents — Chart Planner (works from profile), Insight Writer (works from results).
DuckDB is the tool between them. Rejected: LangGraph (overkill for 2 agents).

**Slide 5: How we handle failure**
- LLM bad JSON → Pydantic catches → retry once
- SQL fails → error + column list back to LLM → retry once
- Still fails → deterministic fallback (chart_engine, R01–R12)
- The user always sees charts, even when the LLM fails entirely.

**Slide 6: Data quality + transparency**
SQL-native cleanup in a VIEW. User sees a plain-English report of every change.
Build trust with non-technical users by being explicit.

**Slide 7: What we cut, and why**
- Multi-user auth → not needed for MVP
- Live data sources → CSV is the assignment
- Custom chart library → Plotly is good enough
- LangGraph → 2 agents don't justify it
- Cloud deploy → Dockerfile is enough for demo

**Slide 8: Production thinking**
- Cost: ~$0.001 per CSV (Haiku is cheap, profile is small)
- Latency: profile + LLM + render ≈ 5–8s for 50k rows
- Failure modes: covered by fallback
- Observability: structured logging at each pipeline step
- Security: no eval, SQL validators, no raw data sent to LLM

**Slide 9: What's missing / what I'd build next**
- Caching (same CSV hash → skip processing)
- User feedback loop (thumbs up/down per chart → fine-tune prompts)
- Multi-file support (joins)
- Persistence (save dashboards)
- Auth + sharing
- Cloud deploy

**Slide 10: Demo flow**
Live walkthrough on Titanic + NYC Airbnb. Show the transparency report.
Show what happens when LLM fails (force a fallback).

---

## 10. The implementation session — how to run it

The next session should:

1. **Read this document first** (load it as a system message or initial user message).
2. **Read the 6 existing files** from `/mnt/user-data/outputs/` (chart_engine, data_quality, profiler, chart_spec, transparency, pipeline).
3. **Follow the spec-kit workflow**:
   - `specify init csv-dashboard --integration claude` (in Claude Code)
   - `/speckit.constitution` — write principles
   - `/speckit.specify` — write the spec
   - `/speckit.plan` — write the plan
   - `/speckit.tasks` — generate task breakdown
   - `/speckit.implement` — execute
4. **Build module by module** in the order listed in Section 4.
5. **Test after each module** — don't write all code then test at the end.
6. **Use the existing code where possible** — don't rewrite chart_engine, data_quality, profiler, chart_spec, transparency. Only refactor the orchestrator.

---

## 11. Open questions / things to confirm with Mahgol before coding

- [ ] OpenRouter API key ready in `.env`?
- [ ] Docker will be installed before deployment phase? (currently not installed)
- [ ] Preferred model for Chart Planner — `anthropic/claude-haiku-4.5` is the default. Cheap and good. Confirm or override.
- [ ] Preferred model for Insight Writer — same as planner, or different?
- [ ] GitHub repo created yet, or create as part of the implementation phase?
- [ ] Streamlit deployment locally only, or also via `streamlit run` inside Docker?

---

## 12. Success criteria for the MVP

The MVP succeeds if:

- [ ] Upload Titanic CSV → dashboard appears in <15 seconds with at least 3 charts and 3 insights.
- [ ] Upload NYC Airbnb CSV → dashboard appears in <30 seconds with at least 3 charts and 3 insights.
- [ ] If the OpenRouter API is unreachable, the dashboard still shows at least 3 charts (from the fallback engine).
- [ ] The transparency report appears for any CSV that has quality issues.
- [ ] A non-technical user can understand the insights without explanation.
- [ ] The code is modular: each file <400 lines, single responsibility.
- [ ] All tests pass (`pytest`).
- [ ] The Docker image builds and runs (when Docker is installed).

---

**End of PROJECT_CONTEXT.md**
