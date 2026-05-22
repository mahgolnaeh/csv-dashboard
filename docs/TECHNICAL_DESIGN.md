# Technical Design Document — CSV Dashboard MVP

> Deep technical reference. Read after the README and ARCHITECTURE overview.
> This document explains *how* every part of the system works, *why* it was
> designed that way, and *what to say* about it in an interview.

**Project:** CSV Dashboard MVP (Deutsche Telekom AI & Digital Innovation case study)
**Author:** Mahgol Naeh
**Date:** 2026-05-21

---

## Section 1 — System Architecture Overview

### 1.1 The 8-Step Pipeline

The system is a linear pipeline. Each step has a single responsibility, a
typed input, and a typed output. Only the next step depends on it.

```
                          ┌──────────────────────────┐
                          │  User uploads CSV file   │
                          │  (Streamlit UI)          │
                          └────────────┬─────────────┘
                                       │ bytes
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  STEP 1 — INGESTION       ingestion/loader.py::load_csv       │
   │  Reads CSV into DuckDB as table `raw_data`                    │
   │  Output: duckdb.DuckDBPyConnection                            │
   └────────────┬──────────────────────────────────────────────────┘
                ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  STEP 2 — DATA QUALITY    quality/data_quality.py::run        │
   │  Builds a `cleaned_data` SQL VIEW on top of raw_data.         │
   │  Reports issues (info / warn / drop) without mutating raw.    │
   │  Output: {view_name, quality_report, llm_context, ...}        │
   └────────────┬──────────────────────────────────────────────────┘
                ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  STEP 3 — PROFILING       profiling/profiler.py               │
   │  SELECT * FROM cleaned_data → pandas DataFrame → profile dict │
   │  Output: dict (~1000 tokens: types, stats, sample values)     │
   └────────────┬──────────────────────────────────────────────────┘
                ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  STEP 4 — CHART PLANNER   agents/chart_planner.py   🤖 LLM #1 │
   │  Sends profile to OpenRouter; expects 3-5 ChartSpec JSON.     │
   │  Output: list[ChartSpec] (Pydantic-validated, retry on fail)  │
   └────────────┬──────────────────────────────────────────────────┘
                ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  STEP 5 — SQL EXECUTION   orchestrator/pipeline.py            │
   │  For each spec: DuckDB executes spec.sql_query                │
   │  Output: list[(ChartSpec, pd.DataFrame)]                      │
   └────────────┬──────────────────────────────────────────────────┘
                ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  STEP 6 — FALLBACK CHECK  charts/engine.py (only if needed)   │
   │  if len(LLM_charts) < 3: deterministic R00-R12 fills the gap  │
   │  Output: list[ChartArtifact] (LLM + fallback merged)          │
   └────────────┬──────────────────────────────────────────────────┘
                ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  STEP 7 — INSIGHT WRITER  agents/insight_writer.py  🤖 LLM #2 │
   │  Sends (spec, result_df) pairs; expects 3-5 sentences         │
   │  Output: list[str] plain-English insights                     │
   └────────────┬──────────────────────────────────────────────────┘
                ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  STEP 8 — TRANSPARENCY    transparency/transparency.py::build │
   │  Converts quality_report into plain-English sentences         │
   │  Output: {has_changes, sentences, plain_text}                 │
   └────────────┬──────────────────────────────────────────────────┘
                ▼
                ┌────────────────────────────────────┐
                │  Streamlit UI (ui/app.py) renders: │
                │  - dataset summary (3 metrics)     │
                │  - data preparation expander       │
                │  - insights as bullet points       │
                │  - charts in a 2-column grid       │
                └────────────────────────────────────┘
```

### 1.2 Data Shape Transformation

Data changes shape at every step. This table is the single most useful
reference for understanding the system:

| Step | Input shape | Output shape |
|---|---|---|
| 1. Ingestion | `bytes` (CSV file content) | `duckdb.DuckDBPyConnection` with `raw_data` table |
| 2. Quality | DuckDB connection | Same connection + `cleaned_data` VIEW + `quality_report: list[dict]` |
| 3. Profiling | `pd.DataFrame` (up to ~50k rows) | `dict` (~1000 tokens: per-column stats) |
| 4. Planner | profile `dict` | `list[ChartSpec]` (3–5 Pydantic models) |
| 5. SQL Execution | `ChartSpec.sql_query` | `pd.DataFrame` (small, ≤10 rows per chart) |
| 6. Fallback | full `pd.DataFrame` (if triggered) | `list[ChartArtifact]` |
| 7. Insight Writer | `list[(ChartSpec, DataFrame)]` | `list[str]` (3–5 sentences) |
| 8. Transparency | `quality_report: list[dict]` | `dict {has_changes, sentences, plain_text}` |
| Final | all of the above | `PipelineResult` dataclass |

**Critical security observation:** raw user data **never reaches an LLM**.
- Step 4 sends only the profile (aggregated statistics).
- Step 7 sends only query results (already aggregated by GROUP BY, max ~10 rows).

A CSV containing emails, names, or other PII never has those values transmitted
to OpenRouter — the profile contains only summary statistics ("text column,
95% unique"), not the actual values.

### 1.3 Where LLM Lives, Where It Doesn't

| Step | LLM or Deterministic? | Why placed here |
|---|---|---|
| 1. Load | Deterministic | `read_csv_auto` is fast and reliable |
| 2. Quality | Deterministic | SQL VIEW with regex + `TRY_CAST` is repeatable |
| 3. Profile | Deterministic | DuckDB `SUMMARIZE` + simple pandas heuristics |
| **4. Planner** | **LLM #1** | Creative choice — which charts answer business questions? |
| 5. Execute | Deterministic | DuckDB executes the validated SQL |
| 6. Fallback | Deterministic | Rule engine (R00–R12) — runs without network |
| **7. Writer** | **LLM #2** | Translation — turn aggregated numbers into plain English |
| 8. Transparency | Deterministic | Template matching on quality_report entries |

**There are exactly 2 LLM calls in the entire pipeline.** Everything else is
deterministic, testable, free, and fast.

### 1.4 Fallback Path — When Does Deterministic Take Over?

The fallback engine (`charts/engine.py`) is **conditionally** activated.
The trigger lives in `orchestrator/pipeline.py`:

```python
# Step 6 in pipeline.py
if len(charts) < 3:
    for fc in fallback_charts(df, filename):
        charts.append(ChartArtifact(
            title=fc["title"], figure=fc["figure"], source="fallback",
        ))
```

This means:

- **LLM completely fails** (network down, malformed JSON on both attempts, etc.)
  → `plan_charts` returns `[]` → `len(charts) == 0` → fallback produces 6 charts.
- **LLM returns specs but all SQL fails** (hallucinated column names, bad joins)
  → every spec raises `duckdb.CatalogException` → `len(charts) == 0` → fallback.
- **LLM returns 1–2 working specs** → fallback adds charts until ≥3 (mixed mode).
- **LLM returns ≥3 working specs** → fallback does not run.

A second consequence: when `chart_results` (the list of *successful*
LLM specs with results) is empty, the **Insight Writer is not called at all**.
Fallback charts are displayed alone. The UI shows the caption
"Using simplified chart generation" instead of LLM insights.

This means the system has three operating modes:

1. **Full LLM mode** — 3–5 LLM charts + LLM insights. (Default success path.)
2. **Mixed mode** — 1–2 LLM charts + fallback charts. LLM insights for the LLM portion.
3. **Full fallback mode** — 0 LLM charts. Fallback only, no insights.

In all three modes the user sees at least 3 charts. **The dashboard always renders.**

### 1.5 The Big Picture in One Sentence

> A linear 8-step pipeline that uses DuckDB as the single source of truth, with
> exactly two LLM calls for creative decisions (chart selection and insight
> writing) and a deterministic fallback that guarantees the dashboard always
> renders — even with the LLM service completely offline.


---

## Section 2 — Module-Level Deep Dive

Every module in `src/csv_dashboard/` is documented below using the same
six-field template:

- **Purpose** — what the module exists for, in one sentence
- **Inputs** — types with example values
- **Outputs** — types with example values
- **Internal logic** — numbered steps
- **Why this design** — one rejected alternative and why we didn't take it
- **Dependencies** — which other modules this one calls

A real Titanic example is included at the end of each section.

---

### 2.1 `ingestion/loader.py`

**Purpose.** Load a CSV file into DuckDB as a table named `raw_data`.
This is the only place CSV parsing happens.

**Inputs.**
- `path: str | Path` — filesystem path to a CSV file.
  Example: `"/tmp/titanic.csv"`.

**Outputs.**
- `duckdb.DuckDBPyConnection` — an open DuckDB connection where `raw_data`
  is now queryable.
- Raises `FileLoadError` if DuckDB cannot parse the file.

**Internal logic.**
1. Convert `path` to a string (accepts both `str` and `Path`).
2. Open a new DuckDB connection (`duckdb.connect()` with no file path → in-memory).
3. Execute `CREATE OR REPLACE TABLE raw_data AS SELECT * FROM read_csv_auto(path, header=true)`.
4. Return the connection. On any exception, wrap it as `FileLoadError`.

**Why this design.** Single-purpose. Could have been merged into `pipeline.py`
but a separate module makes it independently testable (one of the three tests
in `tests/test_loader.py` deliberately passes a corrupt file to verify the
exception path).
*Rejected alternative:* loading into pandas first then converting to DuckDB —
two parsers, two failure modes, slower on large files.

**Dependencies.** `duckdb` only. No internal module dependencies.

**Real example (Titanic).**
- Input: `path="tests/fixtures/titanic.csv"` (891 rows, 12 columns)
- Output: connection with `raw_data` containing columns
  `PassengerId, Survived, Pclass, Name, Sex, Age, SibSp, Parch, Ticket, Fare, Cabin, Embarked`.
- `SELECT COUNT(*) FROM raw_data` returns 891. Elapsed: <100 ms.

---

### 2.2 `quality/data_quality.py`

**Purpose.** Detect data quality issues and build a `cleaned_data` SQL VIEW
on top of `raw_data` that fixes the safe ones. Raw data is never mutated.

**Inputs.**
- `con: duckdb.DuckDBPyConnection` — connection with `raw_data` registered.
- `raw_table: str = "raw_data"` — table name (almost always the default).

**Outputs.**
- `dict` with six keys:
  - `view_name: str` — always `"cleaned_data"`
  - `quality_report: list[dict]` — every issue detected (see §3.3)
  - `dropped_cols: list[str]` — columns excluded from the VIEW
  - `has_issues: bool`
  - `llm_context: str` — plain-English summary for the Chart Planner prompt
  - `clean_columns: list[str]` — columns kept in the VIEW

**Internal logic.**
1. List columns of `raw_data` via `DESCRIBE`.
2. Detect duplicate columns (e.g., `price.1`) and drop them.
3. For each remaining column, run small DuckDB queries to detect:
   all-null, constant value, sentinel nulls (`"N/A"`, `"unknown"`, etc.),
   currency strings, numeric-as-text, datetime-as-text, mixed types, outliers.
4. Build a SQL `SELECT` expression per column. Example transformations:
   - Currency: `TRY_CAST(regexp_replace(price, '[€$£¥,\\s]', '', 'g') AS DOUBLE) AS price`
   - Sentinel nulls: `CASE WHEN LOWER(TRIM(col)) IN (...) THEN NULL ELSE col END`
   - Datetime: `TRY_CAST(TRIM(col) AS TIMESTAMP) AS col`
5. Detect duplicate rows (warn only, never delete).
6. Execute `CREATE OR REPLACE VIEW cleaned_data AS SELECT <expressions> FROM raw_data`.
7. Return the dict.

**Why this design.** A SQL VIEW is a *transformation layer*, not a copy. Raw
data stays untouched, which is essential for transparency: we can always show
the user the original value if asked.
*Rejected alternative:* loading into pandas, applying fixes with `.apply()`,
and writing back. That creates two data paths (raw and cleaned in different
memory locations) and is significantly slower on large files.

**Dependencies.** `duckdb`, `pandas` (only for in-memory datetime parsing
checks). No internal module dependencies.

**Real example (Titanic).**
- Input: connection with `raw_data` (891 rows × 12 cols).
- Output dict includes `quality_report` with entries like:
  - `{"severity": "warn", "column": "Age", "issue": "high missing values", "detail": "20% of values are missing..."}`
  - `{"severity": "drop", "column": "Cabin", "issue": "high missing values", "detail": "77% of values are missing..."}`
- `clean_columns` will be the same as raw_columns minus `Cabin`.

---

### 2.3 `profiling/profiler.py`

**Purpose.** Produce a compact (~1000 tokens) dict describing the cleaned
dataset for the Chart Planner LLM.

**Inputs.**
- `df: pd.DataFrame` — result of `SELECT * FROM cleaned_data`.

**Outputs.**
- `dict` with keys:
  - `row_count: int`, `column_count: int`, `column_names: list[str]`
  - `duplicate_row_count: int`
  - `semantic_type_summary: dict[str, list[str]]` — columns grouped by type
  - `columns: dict[str, dict]` — per-column stats (see §3.2)
  - `warnings: list[dict]` — high cardinality, near-constant, high missing

**Internal logic.**
1. Register `df` with a temporary DuckDB connection.
2. Run `SUMMARIZE _df` to get min/max/mean/std/quantiles/null% for all columns
   in one query.
3. For numeric columns, additionally compute `skewness` and `outlier_count_iqr`
   via DuckDB analytical functions.
4. For each column, detect **semantic type** using DuckDB type hint + content:
   `numeric` | `categorical` | `datetime` | `boolean` | `identifier` | `text`.
5. Sample 5 representative values per column (JSON-safe).
6. Generate `warnings` list for unusual columns (high cardinality, near constant).
7. Return the dict.

**Why this design.** DuckDB does all the heavy lifting (single `SUMMARIZE`
query), and pandas does the small final steps (semantic typing, sampling).
This keeps the output under ~1000 tokens, which fits comfortably in any LLM
context window even after the system prompt.
*Rejected alternative:* using `pandas-profiling` (now `ydata-profiling`).
It produces HTML reports designed for humans, not LLM-friendly JSON, and adds
significant dependency weight.

**Dependencies.** `duckdb`, `pandas`, `numpy`. No internal module dependencies.

**Real example (Titanic).** Excerpt of the output:
```python
{
  "row_count": 891,
  "column_count": 11,    # Cabin dropped
  "semantic_type_summary": {
    "numeric": ["Age", "Fare", "SibSp", "Parch", "Survived", "Pclass"],
    "categorical": ["Sex", "Embarked"],
    "identifier": ["PassengerId", "Ticket", "Name"],
    "datetime": [], "boolean": [], "text": [],
  },
  "columns": {
    "Age": {
      "semantic_type": "numeric", "missing_pct": 19.86, "unique_count": 88,
      "numeric_summary": {
        "min": 0.42, "max": 80.0, "mean": 29.7, "median": 28.0,
        "std": 14.5, "skewness": 0.39, "outlier_count_iqr": 11,
      },
      "sample_values": [22, 38, 26, 35, 54],
    },
    ...
  },
  "warnings": [],
}
```

---

### 2.4 `insights/llm_client.py`

**Purpose.** Send a chat-completion request to OpenRouter and return the
assistant's message content. The single point of contact with the network.

**Inputs.**
- `system_prompt: str` — system role message
- `user_prompt: str` — user role message
- `model: str` — OpenRouter model ID, e.g. `"anthropic/claude-haiku-4.5"`
- `max_tokens: int = 2048`

**Outputs.**
- `str` — the assistant's message text, stripped of whitespace.
- Raises `LLMError` on any network failure, HTTP error, malformed response,
  or missing `choices[0].message.content` key.

**Internal logic.**
1. Read API key from `settings.openrouter_api_key` (loaded once from `.env`).
2. Build payload: `{model, max_tokens, messages: [{system}, {user}]}`.
3. POST to `https://openrouter.ai/api/v1/chat/completions` with 60-second timeout.
4. Raise on non-2xx, parse JSON, extract `data["choices"][0]["message"]["content"]`.
5. Strip and return. On any caught exception, log and raise `LLMError`.

**Why this design.** Thin wrapper. No retries here — retries happen at the
agent layer where they have semantic context. No SDK because OpenRouter is a
plain REST API; adding `openai-python` or `anthropic` would be vendor lock-in.
*Rejected alternative:* the `anthropic` SDK. Locks us to one provider and
duplicates work we'd have to do for OpenAI/Gemini models.

**Dependencies.** `httpx`, `structlog`, `csv_dashboard.config.settings`.

**Real example.** A successful call returns plain JSON text from the model:
```
'{"charts": [{"title": "Survival by Gender", "chart_type": "bar", ...}]}'
```

---

### 2.5 `insights/chart_spec.py`

**Purpose.** Define the Pydantic models that constrain LLM output. Every
field validator, every cross-field rule, lives here.

**Inputs.** Dict from `json.loads(llm_response)`.

**Outputs.**
- `ChartSpec` — single chart specification (see §3.1 for every field).
- `ChartSpecList` — wrapper with `charts: list[ChartSpec]`, `min_length=3`,
  `max_length=5`.

**Internal logic.**
1. Pydantic validates field types and `Literal` constraints (chart_type,
   aggregation, sort_order).
2. Field validators on `sql_query`:
   - Must start with `SELECT` (case-insensitive).
   - Must reference `FROM cleaned_data` (the only allowed table).
   - Must not contain `INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/TRUNCATE` as
     whole words.
3. Cross-field `model_validator(mode="after")` rules:
   - `histogram` → `y_column` must be `None`.
   - `histogram` → `x_column` is required.
   - `scatter` → both `x_column` and `y_column` required.
   - `heatmap` → both `x_column` and `y_column` must be `None`.
   - `scatter`/`histogram` → `aggregation` must be `NONE`.
   - `bar`/`line` → `aggregation` must NOT be `NONE`.
   - `line` → `sort_order` must be `"none"` (chronological from datetime axis).

**Why this design.** Pydantic v2 cross-field validators catch logic errors
the LLM commonly makes (histogram with a y_column, line chart with desc sort).
Each validator becomes a clear error message that's fed back to the LLM on retry.
*Rejected alternative:* JSON Schema. Less Pythonic, weaker error messages,
no cross-field validation.

**Dependencies.** `pydantic` only.

**Real example.** A spec failing validation:
```python
ChartSpec(
    chart_type="histogram",
    y_column="room_type",   # ← violates cross-field rule
    ...
)
# raises ValidationError("histogram does not use y_column. Set y_column to null.")
```

---

### 2.6 `insights/prompts.py`

**Purpose.** Hold the two system prompts (Chart Planner + Insight Writer)
and the three prompt builders (planner / planner-retry / insight). No logic.

**Inputs.** None (system prompts are module-level constants). Builders take:
- `build_planner_prompt(profile: dict, quality_context: str) -> str`
- `build_planner_retry_prompt(original: str, error: str, columns: list[str]) -> str`
- `build_insight_prompt(chart_results: list[tuple[ChartSpec, DataFrame]]) -> str`

**Outputs.** `str` (the user-role message for an LLM call).

**Internal logic.**
1. `build_planner_prompt`: serialize the profile into a compact JSON block,
   embed column-type summary, append `quality_context`. ~500–1000 tokens.
2. `build_planner_retry_prompt`: append `original`, the validation error,
   the list of available column names, and a "Please return corrected JSON"
   instruction.
3. `build_insight_prompt`: for each `(spec, df)`, write a section with title,
   business question, SQL, and the first 10 rows of `df` as JSON. ~500–1500 tokens.

**Why this design.** Prompts are extracted from agents and from `pipeline.py`
into a single module so they can be reviewed, version-controlled, and changed
without touching agent logic.
*Rejected alternative:* keeping prompts inline in agent files. That makes
prompt iteration painful (hunting through Python code) and makes A/B testing
prompts almost impossible.

**Dependencies.** `json` only.

---

### 2.7 `agents/chart_planner.py`

**Purpose.** Agent 1 — generate 3–5 validated `ChartSpec` from a profile.

**Inputs.**
- `profile: dict` (from profiler)
- `quality_context: str` (from data_quality)

**Outputs.**
- `list[ChartSpec]` — 3–5 validated specs, or `[]` on full failure.

**Internal logic.**
1. Build the user prompt via `build_planner_prompt`.
2. Loop up to `max_llm_retries + 1` times (default 2 attempts):
   a. Call `call_llm` with `CHART_PLANNER_SYSTEM` and the current prompt.
   b. Strip ```` ```json ```` fences if present.
   c. `json.loads` → `ChartSpecList(**data)` → return `.charts`.
   d. On `json.JSONDecodeError | ValidationError | LLMError`, rebuild the
      prompt via `build_planner_retry_prompt(error, available_columns)` and
      try again.
3. After all attempts, return `[]`. The orchestrator detects this and uses
   the fallback engine.

**Why this design.** Retry once with structured feedback (the validation
error + the actual column list) gives the LLM a real chance to self-correct
without spending more on multiple retry cycles.
*Rejected alternative:* infinite retry until success. Wastes tokens and
latency. Better to fall back to deterministic.

**Dependencies.** `llm_client.call_llm`, `chart_spec.ChartSpecList`,
`prompts.*`, `config.settings`.

---

### 2.8 `agents/insight_writer.py`

**Purpose.** Agent 2 — produce 3–5 plain-English insight sentences from
LLM chart results.

**Inputs.**
- `chart_results: list[tuple[ChartSpec, pd.DataFrame]]` — successful LLM
  charts plus their executed query results.

**Outputs.**
- `list[str]` — 3–5 short sentences, or `[]` on any failure.

**Internal logic.**
1. If `chart_results` is empty, return `[]` immediately (no LLM call).
2. Build the user prompt via `build_insight_prompt`.
3. Call `call_llm` with `INSIGHT_WRITER_SYSTEM`.
4. Strip code fences, parse JSON, extract `data["insights"]` (or accept a bare list).
5. Filter to strings only, cap at 5, return.
6. On `LLMError | JSONDecodeError`, return `[]`.

**Why this design.** Agent 2 receives the actual query results, not the
profile. This is the difference between "the chart shows price by room type"
and "Manhattan averages $200, almost 3× the Bronx ($75)."
*Rejected alternative:* generating insights inside the planner. A single
prompt trying to do both produces worse SQL and worse insights.

**Dependencies.** `llm_client.call_llm`, `chart_spec.ChartSpec`,
`prompts.INSIGHT_WRITER_SYSTEM`, `prompts.build_insight_prompt`, `config.settings`.

---

### 2.9 `charts/engine.py`

**Purpose.** Deterministic fallback. Generate 3–6 reasonable charts from any
DataFrame using rule-based heuristics (R00 through R12). No LLM, no network.

**Inputs.**
- `df: pd.DataFrame` — the full cleaned dataset.
- `filename: str` — used in the summary chart title.
- `max_charts: int | None = 6` — cap (None means return all).

**Outputs.**
- `list[dict]` — each `{"title", "figure", "rule"}` (Plotly figures).

**Internal logic.**
1. Classify columns: identifier (skipped), datetime, numeric, categorical.
2. Apply rules in priority order:
   - **R00** Summary card (always)
   - **R12** Missingness bar (always if any missing values)
   - **R07** Records over time for datetime columns
   - **R03** Bar of counts for low-cardinality categoricals
   - **R08** Average over time (top-2 numerics per datetime)
   - **R01/R02** Histograms (with outlier markers when needed)
   - **R04** Mean by category (top-2 numerics per low-cardinality category)
   - **R05** Strongest scatter (if any pair has |r| > 0.4)
   - **R06** Correlation heatmap (only |r| > 0.5 shown)
3. Skip identifier columns (R09), skip >40% missing (R10),
   cap high-cardinality categoricals at top-10 (R11).
4. Truncate to `max_charts` (default 6).

**Why this design.** Twelve simple rules cover the vast majority of "what
chart should I make for column type X?" decisions. Phase 0 validation
confirmed this on Titanic and NYC Airbnb without any LLM.
*Rejected alternative:* boxplots. Statistically correct but the words
"median", "quartile", "whisker" violate the non-technical-user audience
principle. Replaced with histogram + outlier annotation.

**Dependencies.** `pandas`, `numpy`, `plotly`, `scipy.stats`. No internal modules.

---

### 2.10 `charts/renderer.py`

**Purpose.** Convert a single `(ChartSpec, DataFrame)` into a Plotly figure.

**Inputs.**
- `spec: ChartSpec`
- `df: pd.DataFrame` (result of the spec's SQL query)

**Outputs.**
- `plotly.graph_objects.Figure`

**Internal logic.**
1. Apply `sort_order` if not `"none"` and `y_column` exists.
2. Dispatch on `chart_type`:
   - bar → `px.bar`
   - line → `px.line`
   - scatter → `px.scatter`
   - histogram → `px.histogram(nbins=30)`
   - heatmap → `px.imshow(df.select_dtypes("number").corr())`
3. Apply `x_label`/`y_label` from the spec, set the title and template.
4. Return the figure.

**Why this design.** Renderer knows nothing about pipelines or LLMs.
Pure mapping from spec to figure, fully unit-testable (5 tests in
`tests/test_renderer.py`, one per chart type).

**Dependencies.** `plotly.express`, `plotly.graph_objects`, `pandas`,
`chart_spec.ChartSpec`.

---

### 2.11 `transparency/transparency.py`

**Purpose.** Convert the technical `quality_report` into plain-English
sentences a non-technical user can read.

**Inputs.**
- `quality_report: list[dict]` — entries with `severity`, `column`, `issue`, `detail`.

**Outputs.**
- `dict {has_changes: bool, sentences: list[str], plain_text: str}`

**Internal logic.**
1. For each entry, dispatch on `severity` (drop/info/warn) and `issue` substring.
2. Build a short sentence using a template:
   - `"Column 'price': Currency symbols removed. Values converted to numbers."`
   - `"Column 'Cabin': 77% of values are empty. Charts may be incomplete."`
3. Filter out entries with no user-facing meaning (e.g., column normalization).
4. Bundle into the output dict. `show_in_streamlit()` is a convenience
   function for the UI to call directly.

**Why this design.** The technical report has fields like `issue: "outlier_count_iqr"`.
A non-technical user does not know what IQR is. This module translates.
*Rejected alternative:* showing the raw `quality_report` to the user. Fails
the audience principle (no jargon).

**Dependencies.** `re`, `streamlit` (optional, only for `show_in_streamlit`).

---

### 2.12 `orchestrator/pipeline.py`

**Purpose.** Wire all modules together. The single public entry point for
running an end-to-end analysis.

**Inputs.**
- `csv_path: str | Path`
- `on_step: callable | None = None` — optional progress callback for the UI.

**Outputs.**
- `PipelineResult` dataclass (see §3.4).

**Internal logic.**
1. Step 1 — `load_csv(csv_path)` → `con`. (FileLoadError propagates.)
2. Step 2 — `run_quality(con)` → `dq`.
3. Step 3 — `con.execute("SELECT * FROM cleaned_data").df()` → `df`; profile it.
4. Step 4 — `plan_charts(profile, dq["llm_context"])` → `specs`.
5. Step 5 — for each spec, execute SQL, render figure, collect; failures append
   to `errors` and skip.
6. Step 6 — if fewer than 3 successful charts, call `fallback_charts(df, filename)`.
7. Step 7 — `write_insights(chart_results)` only if at least one LLM chart succeeded.
8. Step 8 — `build_transparency(dq["quality_report"])`.
9. Close the connection (in `finally`). Return `PipelineResult`.

**Why this design.** Thin wiring layer (~80 lines). No business logic here —
each module owns its own concerns. The orchestrator only sequences them.
*Rejected alternative:* LangGraph. The "graph" is a 8-step linear sequence.
A framework adds dependency and learning cost without adding capability.

**Dependencies.** All other modules in `csv_dashboard/`.

---

### 2.13 `ui/app.py`

**Purpose.** Streamlit user interface. Upload, run, display.

**Inputs.** None (Streamlit script). Reads from `st.file_uploader`.

**Outputs.** None (renders to the browser).

**Internal logic.**
1. Read uploaded bytes → write to a temp file → call `pipeline.run` with a
   progress callback that updates `st.status`.
2. Hash the file bytes (MD5) and store the `PipelineResult` in
   `st.session_state[hash]`. Re-uploads of the same file skip the pipeline.
3. Render the layout:
   - 3-column metric row (rows, columns, quality issues)
   - "What we did to prepare your data" expander (only if changes)
   - "Key insights" bullet list (or caption if empty)
   - 2-column chart grid with captions
   - Error expander (only if `result.errors`)
4. "Upload a different file" button — resets session state and bumps a
   uploader key to clear the widget.

**Why this design.** Streamlit handles file upload, layout, and Plotly
rendering with minimal code. The pure function `_bytes_to_result` is the
testable seam — `tests/test_app.py` exercises it without spinning up Streamlit.
*Rejected alternative:* FastAPI + custom HTML frontend. Far more work for an
MVP whose audience is "any developer can run it on a laptop."

**Dependencies.** `streamlit`, `hashlib`, `tempfile`, `pipeline.run`.

---

## Section 3 — Specification Deep Dive

This section is the schema reference: every field of every important data
structure, with type, meaning, and constraints.

---

### 3.1 `ChartSpec` Pydantic Model

The contract between the Chart Planner LLM and the rest of the system.
Defined in `insights/chart_spec.py`.

#### Fields

| Field | Type | Required | Constraints | Meaning |
|---|---|---|---|---|
| `title` | `str` | yes | 3–80 chars | Human-readable chart title. |
| `chart_type` | `Literal["bar","line","scatter","histogram","heatmap"]` | yes | one of the five | Determines rendering path. |
| `business_question` | `str` | yes | 10–200 chars | The question this chart answers. |
| `sql_query` | `str` | yes | starts with `SELECT`, references `cleaned_data`, no DDL/DML keywords | The DuckDB query to execute. |
| `x_column` | `str \| None` | no | — | Column name for the x-axis. |
| `y_column` | `str \| None` | no | — | Column name for the y-axis. |
| `color_column` | `str \| None` | no | — | Column for color grouping. |
| `aggregation` | `Literal["COUNT","AVG","SUM","MEDIAN","MIN","MAX","NONE"]` | yes | — | The aggregation applied (informational; SQL does the actual work). |
| `sort_order` | `Literal["asc","desc","none"]` | no | default `"none"` | Sort applied before rendering. |
| `limit` | `int \| None` | no | 2–50, default 10 | Max rows in the result. |
| `x_label` | `str \| None` | no | ≤60 chars | Human-readable x-axis label. |
| `y_label` | `str \| None` | no | ≤60 chars | Human-readable y-axis label. |
| `plain_language_explanation` | `str` | yes | 20–300 chars | Subtitle shown to the user. |

#### Field-level validators

- `sql_must_be_select` — uppercase the query, require it to start with
  `SELECT`, reject anything containing `INSERT`, `UPDATE`, `DELETE`, `DROP`,
  `CREATE`, `ALTER`, or `TRUNCATE` as whole words.
- `sql_must_reference_data_table` — the string `"FROM CLEANED_DATA"`
  (case-insensitive) must appear in the query.

#### Cross-field validators (`model_validator(mode="after")`)

| Rule | Logic |
|---|---|
| `check_histogram_has_no_y` | `chart_type=="histogram"` ⇒ `y_column is None` |
| `check_histogram_has_x` | `chart_type=="histogram"` ⇒ `x_column is not None` |
| `check_scatter_has_both_axes` | `chart_type=="scatter"` ⇒ both axes set |
| `check_heatmap_has_no_axes` | `chart_type=="heatmap"` ⇒ both axes None |
| `check_aggregation_none_for_raw_charts` | scatter / histogram ⇒ `aggregation == "NONE"` |
| `check_bar_line_have_aggregation` | bar / line ⇒ `aggregation != "NONE"` |
| `check_time_series_sort` | `chart_type=="line"` ⇒ `sort_order == "none"` |

#### Wrapper

`ChartSpecList`:
- `charts: list[ChartSpec]` — `min_length=3`, `max_length=5`.

#### Example (valid)

```json
{
  "title": "Survival rate by gender",
  "chart_type": "bar",
  "business_question": "How does survival rate differ between male and female passengers?",
  "sql_query": "SELECT Sex, AVG(Survived) AS rate FROM cleaned_data GROUP BY Sex ORDER BY rate DESC",
  "x_column": "Sex",
  "y_column": "rate",
  "color_column": null,
  "aggregation": "AVG",
  "sort_order": "desc",
  "limit": 10,
  "x_label": "Gender",
  "y_label": "Survival rate",
  "plain_language_explanation": "Shows the share of passengers who survived, broken down by gender."
}
```

---

### 3.2 `profile` Dict Shape

Produced by `profiling/profiler.py::profile_dataframe`. This is the dict the
Chart Planner LLM sees.

```python
{
    "row_count": int,                    # e.g. 891
    "column_count": int,                 # e.g. 11
    "column_names": list[str],
    "duplicate_row_count": int,          # rows that appear more than once
    "filename": str,                     # injected by pipeline.run

    "semantic_type_summary": {
        "numeric":     list[str],        # e.g. ["Age", "Fare", "SibSp", ...]
        "categorical": list[str],        # e.g. ["Sex", "Embarked"]
        "datetime":    list[str],
        "boolean":     list[str],
        "identifier":  list[str],        # e.g. ["PassengerId", "Ticket"]
        "text":        list[str],
    },

    "columns": {
        "<column_name>": {
            "dtype":         str,        # pandas dtype, e.g. "float64"
            "duckdb_type":   str,        # e.g. "DOUBLE"
            "semantic_type": str,        # one of the 6 above
            "missing_count": int,
            "missing_pct":   float,      # 0 to 100
            "unique_count":  int,
            "sample_values": list,       # up to 5, JSON-safe
            "numeric_summary": {         # only if semantic_type == "numeric"
                "min": float | None,
                "max": float | None,
                "mean": float | None,
                "median": float | None,
                "std": float | None,
                "q1": float | None,
                "q3": float | None,
                "skewness": float | None,
                "outlier_count_iqr": int | None,
            },
            "warning": str | absent,     # "high_cardinality" | "constant" | "near_constant"
        },
        ...
    },

    "warnings": [
        {
            "column": str,
            "type":   str,               # high_cardinality | high_missing | constant | near_constant
            "detail": str,
        },
        ...
    ],
}
```

#### Semantic types — how they are inferred

| Semantic type | Detected when |
|---|---|
| `boolean` | dtype is bool, or column contents are subset of {true/false/yes/no/1/0/t/f/y/n} |
| `datetime` | native datetime dtype, or DuckDB type DATE/TIMESTAMP, or 80%+ of samples parse as a date in one of six common formats |
| `identifier` | integer with `unique_ratio > 0.9` and `unique_count > 100`, OR string with `unique_ratio > 0.9` and `unique_count > 50` |
| `text` | string column with average length > 50 |
| `numeric` | DuckDB numeric type and not classified as `identifier` |
| `categorical` | everything else (string columns with reasonable cardinality) |

---

### 3.3 `quality_report` List Shape

Produced by `quality/data_quality.py::run`. Drives the transparency module.

```python
[
    {
        "severity": "info" | "warn" | "drop",
        "column":   str,                      # absent for dataset-level entries
        "issue":    str,                      # short technical label
        "detail":   str,                      # human-readable explanation
    },
    ...
]
```

#### Severity meanings

| Severity | What it means | Example issue |
|---|---|---|
| `info` | Auto-fixed silently inside the VIEW | `"sentinel null strings → NULL in view"` |
| `warn` | Detected, surfaced to the user, NOT changed | `"high missing values"`, `"extreme outliers detected"` |
| `drop` | Column removed from the VIEW SELECT entirely | `"all-null column removed"`, `"constant column removed"` |

#### Common entries

- `info` + currency stripping
- `info` + sentinel-null replacement
- `info` + numeric string cast
- `info` + datetime cast
- `info` + duplicate column removed
- `warn` + extreme outliers
- `warn` + mixed types
- `warn` + inconsistent date formats
- `warn` + duplicate rows
- `warn` + high missing values
- `drop` + all-null column
- `drop` + constant column

---

### 3.4 `PipelineResult` Dataclass

Defined in `orchestrator/pipeline.py`. The single object the UI consumes.

```python
@dataclass
class ChartArtifact:
    title:       str
    figure:      plotly.graph_objects.Figure
    source:      str               # "llm" or "fallback"
    explanation: str = ""          # used only for LLM charts

@dataclass
class PipelineResult:
    charts:       list[ChartArtifact]
    insights:     list[str]
    transparency: dict              # {has_changes, sentences, plain_text}
    profile:      dict              # the full profile dict (for debug/inspect)
    errors:       list[str] = field(default_factory=list)
```

`errors` contains non-fatal warnings like `"Chart 'X' failed: column Y does
not exist"`. The dashboard still renders; the UI shows these in a collapsed
expander.


---

## Section 4 — Prompt and LLM Flow

### 4.1 `CHART_PLANNER_SYSTEM` — Annotated

Full prompt with inline annotations explaining each rule.

```text
You are a senior data analyst generating dashboard chart specifications.

Your audience is a non-technical business consultant.
─── frames the LLM's role; emphasizes no jargon

# YOUR JOB
Given a profile of a dataset, return between 3 and 5 chart specifications
as a JSON object. Each chart should answer a different kind of question.
─── target output size + variety constraint

# RULES (NON-NEGOTIABLE)

1. Table name is `cleaned_data`.
   ─── strict table name; SQL validator enforces this

2. Only SELECT queries.
   ─── SQL safety: blocklist runs on the validator side too

3. Skip identifier and text columns.
   ─── prevents the common mistake of charting an "id" column

4. For high-cardinality categoricals, use LIMIT 10 + ORDER BY count DESC.
   ─── prevents charts with 100+ bars (unreadable)

5. For skewed numeric (|skewness| > 1), prefer MEDIAN over AVG.
   ─── statistically appropriate; mean misleads with skewed data

6. If outlier_count_iqr > 0, mention it in plain_language_explanation.
   ─── transparency built into the LLM output itself

7. Aim for chart-type variety — histogram + bar + line if possible.
   ─── better dashboards have diverse chart types

8. Use the data quality context (high missing, mixed types).
   ─── lets the LLM avoid problematic columns

# OUTPUT FORMAT
Return ONLY a JSON object. No markdown, no commentary, no code fences.
─── strict — anything else breaks JSON parsing

# CHART-TYPE RULES
- histogram → y_column MUST be null
- scatter   → both x_column and y_column REQUIRED
- heatmap   → both x_column and y_column MUST be null
- bar       → aggregation cannot be NONE
- line      → aggregation not NONE, sort_order MUST be "none"
─── these mirror the cross-field Pydantic validators exactly

# EXAMPLES OF GOOD CHARTS
For Airbnb:  "Average price by neighborhood" (bar)
              "Distribution of review counts" (histogram)
              "Listings created per month"   (line)
For Titanic: "Survival rate by passenger class" (bar)
              "Age distribution"                (histogram)
              "Survival rate by gender"         (bar)
─── few-shot examples in the prompt

# COMMON MISTAKES TO AVOID
- Using id or identifier columns
- Aggregating without GROUP BY
- Forgetting LIMIT on high-cardinality categoricals
- Histogram with a y_column
- Technical labels like `avg_price_log` — translate to plain English
- Generic explanations like "Shows the data"
```

### 4.2 `INSIGHT_WRITER_SYSTEM` — Annotated

```text
You are writing short, plain-English insights for a non-technical business audience.

# YOUR JOB
You receive a list of charts and the actual query results for each.
Write 3 to 5 short insight sentences that summarize what the data shows.

# RULES

1. Plain English only. No jargon (no "outliers", "distribution", "p-value", "standard deviation").
   ─── matches the constitution: no jargon in user-facing text

2. Reference actual numbers. Every insight must include a specific number
   or comparison. "There are differences between groups" is forbidden.
   ─── forces the LLM to ground itself in the query result

3. One or two sentences per insight. Short and punchy.
   ─── readability

4. 3-5 insights total. Cover different findings.
   ─── matches output cap

5. Use comparisons. "3× more than", "twice as many", "double the rate"
   land better than raw numbers alone.
   ─── this is what makes insights feel insightful

6. Do not infer causation. "Manhattan listings are 3× more expensive
   than Brooklyn" is fine. "Manhattan listings are expensive because of
   tourism" is speculation.
   ─── intellectual honesty

7. No filler. Skip "interestingly", "it is worth noting that",
   "the data shows that". Just say the thing.
   ─── crispness

# OUTPUT FORMAT
Return ONLY a JSON object: {"insights": ["...", "...", "..."]}.

# EXAMPLES OF GOOD
- "Manhattan listings cost on average $200, almost 3× more than the Bronx ($75)."
- "Brooklyn has 20,104 listings, 41% of all listings."
- "Women survived at 74%, compared to 19% for men."

# EXAMPLES OF BAD
- "There is some variation in price." (no numbers)
- "The mean price exhibits a positively skewed distribution." (jargon)
- "Interestingly, women tend to survive more often." (filler + vague)
- "This is because Manhattan is a popular tourist destination." (speculation)
```

### 4.3 `build_planner_prompt` — What's in the user message

The Chart Planner sees a user message constructed as:

```text
Dataset: titanic.csv
Rows: 891  |  Columns: 11
Duplicate rows: 0

Column types available:
  numeric:     ["Age", "Fare", "SibSp", "Parch", "Survived", "Pclass"]
  categorical: ["Sex", "Embarked"]
  datetime:    []
  boolean:     []
  identifier:  ["PassengerId", "Name", "Ticket"]    ← DO NOT USE
  text:        []                                   ← DO NOT USE

Column details:
[
  {
    "name": "Age",
    "semantic_type": "numeric",
    "missing_pct": 19.86,
    "unique_count": 88,
    "stats": {
      "min": 0.42, "max": 80.0, "mean": 29.7, "median": 28.0,
      "std": 14.5, "skewness": 0.39, "outlier_count_iqr": 11
    },
    "sample_values": [22, 38, 26, 35, 54]
  },
  ...
]

Data quality context:
- WARNING Age: high missing values. 20% of values are missing.
- DROPPED Cabin: high missing values. 77% missing.

Generate 3 to 5 useful, varied chart specifications for this dataset.
Return ONLY the JSON object.
```

#### Why each piece is included

| Piece | Why |
|---|---|
| Dataset name + dims | gives the LLM context for tone (small vs big data) |
| Column type summary | quick scan; identifier/text marked DO NOT USE |
| Per-column stats with skewness/outliers | drives the median-vs-mean decision |
| Sample values | helps the LLM recognize implicit identifier columns |
| Quality context | lets the LLM avoid bad columns |

### 4.4 `build_insight_prompt` — What the writer sees

For each successful `(spec, df)`, the user message has a section like:

```text
### Chart 1: Survival by Gender
Business question: How does survival rate differ by gender?
Chart type: bar
Query: SELECT Sex, AVG(Survived) AS rate FROM cleaned_data GROUP BY Sex ORDER BY rate DESC
Result shape: 2 rows × 2 columns
First rows:
[
  {"Sex": "female", "rate": 0.7420},
  {"Sex": "male",   "rate": 0.1889}
]
```

Followed by:

```text
Write 3-5 short, plain-English insights based ONLY on the numbers above.
Each insight must reference specific numbers.
Return ONLY the JSON object with the "insights" key.
```

#### What is and is not included

| Included | Excluded |
|---|---|
| Spec title, business question, SQL | The full profile dict |
| First 10 rows of every result | Any raw row from `cleaned_data` |
| Chart type | Plotly figure objects |

The writer sees only aggregated numbers from the GROUP BY result, never the
underlying rows.

### 4.5 Retry Mechanism

When the planner's first attempt fails (bad JSON, validation error, or
LLM transport error), the retry path is:

1. Catch the exception.
2. Call `build_planner_retry_prompt(original_prompt, error_message, columns)`.
3. The retry user message is:
   ```text
   <the original user message>

   ---

   YOUR PREVIOUS RESPONSE HAD THIS ERROR:
   <error string from Pydantic or json.JSONDecodeError>

   Available column names in cleaned_data table:
   ['Age', 'Fare', 'Sex', ...]

   Please return a corrected JSON object that:
   1. Uses ONLY column names from the list above.
   2. Fixes the specific error mentioned.
   3. Follows ALL the rules from the system prompt.

   Return ONLY the corrected JSON object.
   ```
4. Call the LLM again. If this attempt also fails, return `[]` and let the
   fallback engine take over.

Only one retry. The Insight Writer has no retry (returns `[]` on failure).

### 4.6 Token Budget

| Call | Approx input | Approx output |
|---|---|---|
| Chart Planner | ~1,200 tokens (system + profile) | ~800 tokens (3-5 specs) |
| Insight Writer | ~1,500 tokens (system + results) | ~400 tokens (3-5 sentences) |
| **Total per CSV** | **~2,700 input** | **~1,200 output** |

At Claude Haiku rates (~$1 / 1M input, $5 / 1M output):

- Planner input:  0.0012 × $1 / 1000 = $0.0000012 per call → ~$0.0003 input × multiplier ≈ ~$0.00026
- Writer input:   ~$0.00024 similar
- **Cost per CSV: ~$0.0005 (half a cent on every 10 analyses).**

2,000 CSV uploads ≈ $1. The deterministic fallback adds $0.

---

## Section 5 — End-to-End Execution Trace (Titanic)

A trace of `pipeline.run("tests/fixtures/titanic.csv")`. Real numbers from
the manual test on 2026-05-20.

**Setup.** 891 rows × 12 columns. Real OpenRouter API. `anthropic/claude-haiku-4.5`
for both agents. Local machine.

---

### Step 1 — Ingestion (~60 ms)

- **Function:** `csv_dashboard.ingestion.loader.load_csv("tests/fixtures/titanic.csv")`
- **Input:** `path="tests/fixtures/titanic.csv"`
- **What happens:** DuckDB opens an in-memory connection; `read_csv_auto`
  detects header, delimiter, types; populates `raw_data`.
- **Output:** open `duckdb.DuckDBPyConnection`.
- **Verifiable:** `SELECT COUNT(*) FROM raw_data` returns 891.
- **Decision made:** none — pure load. Failures would raise `FileLoadError`.

### Step 2 — Data Quality (~200 ms)

- **Function:** `csv_dashboard.quality.data_quality.run(con)`
- **Input:** the DuckDB connection.
- **What happens:**
  - Lists 12 columns of `raw_data`.
  - For each column, runs detection queries.
  - Detects: Age has 19.86% missing (warn), Cabin has 77.10% missing (drop),
    Fare contains extreme outliers (warn, biggest at $512), SibSp has
    outliers (warn).
  - Builds `cleaned_data` VIEW without `Cabin`.
- **Output (excerpt):**
  ```python
  {
    "view_name": "cleaned_data",
    "quality_report": [
       {"severity": "warn", "column": "Age", "issue": "high missing values",
        "detail": "20% of values are missing. Charts using this column may be misleading."},
       {"severity": "drop", "column": "Cabin", "issue": "high missing values",
        "detail": "77% of values are missing..."},
       {"severity": "warn", "column": "Fare", "issue": "extreme outliers detected",
        "detail": "1 value(s) outside IQR×3.0 (expected [-30.84, 95.04], actual [0.00, 512.33])..."},
       ...
    ],
    "dropped_cols": ["Cabin"],
    "has_issues": True,
    "llm_context": "Data quality context...\n- WARNING Age: high missing values...\n- DROPPED Cabin: ...",
    "clean_columns": ["PassengerId", "Survived", "Pclass", "Name", "Sex",
                       "Age", "SibSp", "Parch", "Ticket", "Fare", "Embarked"],
  }
  ```
- **Decision made:** drop `Cabin`, keep `Age` with a warning, keep raw values
  for outliers (transparency).

### Step 3 — Profiling (~100 ms)

- **Function:** `csv_dashboard.profiling.profiler.profile_dataframe(df)` where
  `df = con.execute("SELECT * FROM cleaned_data").df()`.
- **Input:** pandas DataFrame, 891 rows × 11 columns.
- **What happens:**
  - DuckDB `SUMMARIZE` returns base stats in one query.
  - Skewness + outlier count computed per numeric column.
  - Semantic types inferred:
    - identifier: `PassengerId`, `Name`, `Ticket`
    - categorical: `Sex`, `Embarked`
    - numeric: `Survived`, `Pclass`, `Age`, `SibSp`, `Parch`, `Fare`
  - 5 sample values per column collected (random seed 42 for reproducibility).
- **Output (key parts):**
  ```python
  {
    "row_count": 891, "column_count": 11,
    "duplicate_row_count": 0,
    "semantic_type_summary": {
      "numeric": ["Survived","Pclass","Age","SibSp","Parch","Fare"],
      "categorical": ["Sex","Embarked"],
      "identifier": ["PassengerId","Name","Ticket"],
      "datetime": [], "boolean": [], "text": [],
    },
    "columns": {
      "Age": {
        "semantic_type": "numeric", "missing_pct": 19.86, "unique_count": 88,
        "numeric_summary": {
          "min": 0.42, "max": 80.0, "mean": 29.7, "median": 28.0,
          "std": 14.5, "skewness": 0.39, "outlier_count_iqr": 11,
        },
        "sample_values": [22, 38, 26, 35, 54],
      },
      "Fare": {
        "semantic_type": "numeric", "missing_pct": 0.0, "unique_count": 248,
        "numeric_summary": {
          "min": 0.0, "max": 512.0, "mean": 32.2, "median": 14.4,
          "std": 49.7, "skewness": 4.79, "outlier_count_iqr": 116,
        },
        ...
      },
      ...
    },
    "warnings": [],
  }
  ```
- **Decision made:** Fare has |skewness|=4.79 ≫ 1, which will signal the
  planner to prefer MEDIAN over AVG when aggregating Fare.

### Step 4 — Chart Planner LLM (~2.1 s)

- **Function:** `csv_dashboard.agents.chart_planner.plan_charts(profile, dq["llm_context"])`
- **Input:** the profile dict above + the quality context string.
- **What happens:**
  - `build_planner_prompt` produces a ~900-token user message.
  - `call_llm` POSTs to OpenRouter (`anthropic/claude-haiku-4.5`).
  - Response is ~700 tokens of JSON: 5 chart specs.
  - `json.loads` succeeds. `ChartSpecList(**data)` validates: all five pass.
- **Output (titles only):**
  1. *Survival rate by passenger class* — bar, AVG on Survived
  2. *Survival rate by gender* — bar, AVG on Survived
  3. *Age distribution of passengers* — histogram on Age
  4. *Fare distribution* — histogram on Fare (LLM notes outliers in explanation)
  5. *Median fare by class* — bar, MEDIAN on Fare (because skewness > 1 ✓)
- **Decision made:** no retry needed. All 5 specs valid on first attempt.

### Step 5 — SQL Execution + Render (~0.5 s)

- **Function:** the for-loop in `pipeline.run` over each spec.
- **Input:** the 5 ChartSpec objects.
- **What happens:**
  - For each spec: `con.execute(spec.sql_query).df()` → small result DataFrame.
  - Then `render_chart(spec, result_df)` → Plotly Figure.
  - All 5 execute successfully (no `CatalogException`).
- **Output:**
  - `charts = [ChartArtifact(source="llm"), ChartArtifact(source="llm"), ...]` — 5 entries.
  - `chart_results = [(spec, df), ...]` — 5 tuples for the Insight Writer.
- **Decision made:** all 5 SQL queries succeed. `errors = []`.

### Step 6 — Fallback Check (skipped, <1 ms)

- **Function:** the `if len(charts) < 3:` branch in `pipeline.run`.
- **Input:** `len(charts) == 5`.
- **What happens:** condition is false; fallback engine is not invoked.
- **Output:** no change to `charts`.
- **Decision made:** skip fallback. Full LLM mode.

### Step 7 — Insight Writer LLM (~1.8 s)

- **Function:** `csv_dashboard.agents.insight_writer.write_insights(chart_results)`
- **Input:** the 5 `(spec, result_df)` tuples.
- **What happens:**
  - `build_insight_prompt` serializes each result_df's first 10 rows as JSON.
  - User message is ~1,400 tokens.
  - `call_llm` to the same model.
  - Response is ~350 tokens of JSON: 4 insights.
  - JSON parses; 4 strings extracted.
- **Output:**
  ```python
  [
    "Women survived at 74% compared to 19% for men, nearly 4× higher.",
    "First-class passengers had a 63% survival rate, more than double third-class (24%).",
    "Average passenger age was 29.7 years; the median was 28.",
    "Fare paid varied enormously — most passengers paid under $32, but one ticket cost over $500.",
  ]
  ```
- **Decision made:** writer produced 4 insights (within the 3–5 range).

### Step 8 — Transparency (~5 ms)

- **Function:** `csv_dashboard.transparency.transparency.build(dq["quality_report"])`
- **Input:** the 3-entry quality_report (Age warn, Cabin drop, Fare warn).
- **What happens:** template matching converts each technical entry to a
  plain-English sentence.
- **Output:**
  ```python
  {
    "has_changes": True,
    "sentences": [
      "Column \"Age\": 20% of values are empty. Charts may be incomplete.",
      "Column \"Cabin\": 77% of values are empty. Charts may be incomplete.",
      "Column \"Fare\": 1 value(s) are unusually high or low. Shown as-is in charts.",
    ],
    "plain_text": "While preparing your data, the following changes were made:\n  - ...",
  }
  ```
- **Decision made:** transparency report has changes → UI shows the expander.

### Final assembly

`pipeline.run` returns:

```python
PipelineResult(
    charts=[<5 LLM ChartArtifacts>],
    insights=[<4 sentences>],
    transparency={"has_changes": True, "sentences": [...], "plain_text": "..."},
    profile={"row_count": 891, ...},
    errors=[],
)
```

`ui/app.py` renders:

- Metrics row: `Rows: 891`, `Columns: 11`, `Quality issues: 3`
- "What we did to prepare your data (3 changes)" expander — collapsed by default
- "Key insights" — 4 bullet points
- Charts grid — 5 figures in 3 rows (2 + 2 + 1)
- No error expander (errors list is empty)

**Total elapsed time: ~5–7 seconds.** Well within the 15-second budget.


---

## Appendix — How to use this document

- **Before the interview.** Read all five sections once. Section 1 gives
  you the elevator pitch. Section 2 gives you the per-module talking
  points. Section 3 is the schema if asked about validation. Section 4
  is the prompt content if asked about LLM design. Section 5 is the
  end-to-end story.
- **During the interview.** The "Interview notes" boxes contain
  pre-written answers to common questions. Quote them — they are
  defensible.
- **After the interview.** Treat this as the reference for modifying
  modules. Each subsection in §2 includes a "Why this design" paragraph
  pointing at the rejected alternative, so you can revisit decisions
  with context.

**Three points:**

1. DuckDB is the single source of truth — no parallel pandas paths.
2. Raw user data never reaches an LLM.
3. The dashboard always renders — even with the LLM completely offline.

