# Specification: CSV Dashboard MVP

> What we're building and why. Not how.

---

## 1. The Problem

A non-technical user has a CSV file. They want to understand it.

They cannot:
- Write code.
- Read statistical jargon (mean vs. median, IQR, skewness, p-values).
- Configure tools or pick chart types.
- Trust black boxes — they want to see what was done to their data.

They want:
- To upload a file and get a dashboard immediately.
- Charts that answer real business questions, not generic plots.
- Plain-English insights about what the data shows.
- Confidence that nothing weird happened to their data behind the scenes.

The system must work for any CSV — from a 200-row survey export to a
50,000-row sales log — without prior knowledge of the schema.

---

## 2. User Stories

### US-1: Upload a CSV

**As a** non-technical user
**I want to** drag and drop a CSV file
**So that** I can analyze it without writing any code.

Acceptance:
- The UI has a single, obvious upload area.
- Files up to 100 MB are accepted.
- An invalid file produces a clear error: "This file could not be read as a CSV. Please check the format."

### US-2: See a dashboard automatically

**As a** non-technical user
**I want to** see charts that summarize my data
**So that** I can understand it without thinking about chart types.

Acceptance:
- After upload, at least 3 charts appear.
- Each chart has a clear title and a one-sentence explanation.
- Charts answer different kinds of questions (not 3 versions of the same plot).
- The dashboard loads in under 30 seconds for files up to 50k rows.

### US-3: Read plain-English insights

**As a** non-technical user
**I want to** read short summary sentences about my data
**So that** I get the key findings without studying every chart.

Acceptance:
- 3–5 short insights appear above or beside the charts.
- Each insight is one or two sentences in plain English.
- Insights reference actual numbers from the data ("Brooklyn has 25% more listings than Manhattan"), not generic observations ("there are differences between groups").

### US-4: See what was done to my data

**As a** non-technical user
**I want to** see a clear list of changes the system made
**So that** I trust the analysis is honest.

Acceptance:
- A "data preparation" section is visible (collapsed by default).
- It lists every change in plain English:
  - "Column 'price': Currency symbols removed."
  - "Column 'empty': No data found. Removed from analysis."
  - "Column 'score': 1 value is unusually high. Shown as-is in charts."
- No technical jargon.
- If nothing was changed, the section says so.

### US-5: Work across domains and sizes

**As a** developer evaluating this system
**I want to** upload very different CSVs
**So that** I can confirm the system adapts without configuration.

Acceptance:
- Titanic CSV (891 rows, mixed types) → dashboard works.
- NYC Airbnb 2019 CSV (48k rows, dates, geo) → dashboard works.
- A user-provided CSV from a different domain → dashboard works without code changes.

### US-6: Handle LLM failures gracefully

**As a** user when the AI service is unavailable
**I want to** still see a useful dashboard
**So that** my work isn't blocked.

Acceptance:
- If the LLM API is unreachable or returns invalid output, charts still appear.
- The charts come from a deterministic fallback engine.
- The user sees a small note: "Using simplified chart generation" (not an error).

---

## 3. Functional Requirements

### FR-1: Ingestion
- Accept CSV uploads via Streamlit's `st.file_uploader`.
- Load directly into DuckDB using `read_csv_auto`.
- Auto-detect header, delimiter, and column types.
- Reject files that DuckDB cannot parse with a clear error.

### FR-2: Data Quality
- Detect and report:
  - Sentinel nulls ("N/A", "unknown", "-").
  - Currency symbols in numeric-like columns.
  - Numbers stored as text.
  - Datetime strings.
  - Whitespace.
  - Mixed types (numeric + text in same column).
  - Inconsistent date formats.
  - Duplicate rows.
  - Duplicate columns (e.g., `price.1`).
  - All-null columns.
  - Constant columns (single unique value).
  - Columns with >40% missing values.
  - Extreme outliers (IQR × 3).
- Auto-fix safe issues by building a `cleaned_data` SQL VIEW.
- Never mutate the raw table.

### FR-3: Profiling
- For each column in `cleaned_data`, compute:
  - Semantic type (numeric, categorical, datetime, boolean, identifier, text).
  - Missing count and percentage.
  - Unique count.
  - 5 sample values.
  - For numeric: min, max, mean, median, std, q1, q3, skewness, outlier count.
- Build a structured profile dict under 2000 tokens.

### FR-4: Chart Planner Agent
- Send the profile + quality context to an LLM.
- Receive 3–5 chart specifications as JSON.
- Each spec includes: title, chart_type, business_question, sql_query, x_column, y_column, color_column, aggregation, sort_order, limit, x_label, y_label, plain_language_explanation.
- Validate every spec with Pydantic.
- On validation failure: retry once with the error message included in the prompt.

### FR-5: SQL Execution
- Validate every SQL query:
  - Must start with `SELECT`.
  - Must reference `cleaned_data`.
  - Must not contain `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `TRUNCATE`.
- Execute the query against DuckDB.
- On SQL error: retry once with the error message and available column names sent to the LLM.

### FR-6: Insight Writer Agent
- After SQL execution, send (chart_spec, result_df) pairs to a second LLM.
- Receive 3–5 short insight sentences.
- Each sentence must:
  - Reference actual numbers from the data.
  - Be one or two sentences.
  - Use plain English (no statistical terms).

### FR-7: Chart Rendering
- Render each spec + result as a Plotly figure.
- Apply x_label, y_label, sort_order, color_column, limit.
- Add plain_language_explanation as a subtitle annotation.

### FR-8: Fallback Engine
- A rule-based chart generator that requires no LLM.
- Implements R01–R12 as described in the constitution.
- Activates when the LLM produces fewer than 3 valid charts.
- Produces a dataset summary card and a missingness chart regardless of LLM state.

### FR-9: Transparency
- Convert the data quality report into plain-English sentences.
- Group by severity: removed, warning, fixed.
- Display in the UI as a collapsible section.
- All text in English. No technical terms.

### FR-10: UI
- Single-page Streamlit app.
- Upload area at the top.
- Loading spinner with a message during processing.
- Dataset summary (row count, column count).
- Data preparation section (collapsible).
- Insights section (bulleted list of plain sentences).
- Charts section (grid layout, 2 charts per row).
- Error banner for fatal failures.

---

## 4. Non-Functional Requirements

### NFR-1: Performance
- Titanic CSV (891 rows): full dashboard in <15 seconds.
- NYC Airbnb CSV (48k rows): full dashboard in <30 seconds.
- LLM calls in parallel where possible.

### NFR-2: Cost
- A single CSV analysis must cost less than $0.01 in LLM fees with default models.
- Default models: `anthropic/claude-haiku-4.5` for both agents.

### NFR-3: Reliability
- The dashboard renders successfully on a CSV with any combination of:
  - All null values in some columns.
  - Mixed types.
  - 0 rows of data (empty file).
  - 1 row of data.
  - 50,000+ rows.
  - Single column.
  - 100+ columns.

### NFR-4: Security
- The OpenRouter API key is loaded from `.env` only.
- No raw data is sent to the LLM — only aggregated profile statistics.
- SQL queries are validated before execution; dangerous keywords are rejected.
- No use of `eval`, `exec`, or `pickle.loads` on user input.

### NFR-5: Observability
- Each pipeline step logs:
  - Start time, end time, duration.
  - Number of inputs/outputs.
  - Any errors with full context.
- Logs are structured (JSON-formatted) and go to stdout.

### NFR-6: Reproducibility
- All dependencies pinned in `pyproject.toml`.
- A `Dockerfile` builds and runs the system identically on any machine.
- Tests pass in CI with mocked LLM calls.

### NFR-7: Maintainability
- Every module has a single responsibility.
- Each file is under 400 lines (soft limit).
- Type hints on all public functions.
- Tests for every module with logic.

---

## 5. Interfaces

### 5.1 Pipeline Entry Point

```python
def run(csv_path: str) -> PipelineResult:
    """
    Run the full pipeline on a CSV.

    Returns a PipelineResult with:
      - charts: list[ChartArtifact]   (title, figure, source: "llm"|"fallback")
      - insights: list[str]           (plain-English sentences)
      - transparency: TransparencyReport
      - profile: dict                 (for debugging / "view raw" toggle)
      - errors: list[str]             (non-fatal warnings)
    """
```

### 5.2 LLM Client

```python
def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int = 2048,
) -> str:
    """
    Call OpenRouter and return the assistant's message content.
    Raises LLMError on network or API failure.
    """
```

### 5.3 Each Agent

```python
def plan_charts(profile: dict, quality_context: str) -> list[ChartSpec]:
    """Returns 3-5 validated chart specs. Empty list if all attempts fail."""

def write_insights(
    chart_results: list[tuple[ChartSpec, pd.DataFrame]],
) -> list[str]:
    """Returns 3-5 plain-English insights. Empty list if LLM fails."""
```

---

## 6. Out of Scope

These items are **not** in this spec. They are listed here so they aren't
silently considered:

- User authentication, accounts, or sharing.
- Saving or loading past dashboards.
- Multi-file joins.
- Live database connections.
- Custom chart types beyond Plotly built-ins.
- Mobile-optimized UI.
- A REST API or CLI beyond the Streamlit UI.
- Real-time data updates.
- Cloud deployment automation (only a Dockerfile is in scope).
- Multi-language UI (English only).
- Fine-tuning or custom models.

---

## 7. Acceptance Criteria for the MVP

The MVP is considered complete when **all** of the following are true:

- [ ] Uploading the Titanic CSV produces a dashboard with ≥3 charts and ≥3 insights, in <15 seconds.
- [ ] Uploading the NYC Airbnb CSV produces a dashboard with ≥3 charts and ≥3 insights, in <30 seconds.
- [ ] With the OpenRouter API key removed, the dashboard still produces ≥3 charts.
- [ ] The transparency report appears whenever the CSV has quality issues.
- [ ] No file exceeds 400 lines of code.
- [ ] `pytest` passes with mocked LLM calls.
- [ ] `docker build` succeeds.
- [ ] The README explains how to run the system locally and in Docker.
- [ ] A 5–10 slide presentation explains architecture, trade-offs, and what's missing.

---

**End of Specification. Version 1.0. Date: 2026-05-19.**
