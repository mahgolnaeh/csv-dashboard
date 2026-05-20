# Architecture

> Deep dive into the CSV Dashboard pipeline design.

---

## The 9-Step Pipeline

```
[1] CSV upload (Streamlit st.file_uploader)
        |
        v
[2] DuckDB ingestion
    loader.load(path) -> DuckDB connection
    CREATE TABLE raw_data AS SELECT * FROM read_csv_auto(path)
        |
        v
[3] Data quality
    data_quality.run(con) -> cleaned_data VIEW + quality_report
    Fixes applied as SQL expressions (raw_data is never mutated)
        |
        v
[4] Profiling
    profiler.profile_dataframe(df) -> profile dict (~1000 tokens)
    Semantic types, per-column stats, warnings
        |
        v
[5] Agent 1: Chart Planner
    chart_planner.plan_charts(profile, quality_context)
    -> calls OpenRouter LLM
    -> returns 3-5 ChartSpec objects (Pydantic-validated JSON)
        |
        v
[6] Pydantic + SQL validation
    Each ChartSpec validated: structure, SQL safety, cross-field rules
    On failure: retry LLM once with the error message appended
    On second failure: spec dropped; fallback fills the gap
        |
        v
[7] DuckDB executes each spec.sql_query on cleaned_data
    -> result DataFrames
        |
        v
[8] Agent 2: Insight Writer
    insight_writer.write_insights([(spec, result_df), ...])
    -> calls OpenRouter LLM with actual query results (not raw data)
    -> returns 3-5 plain-English insight strings
        |
        v
[9] Plotly renders + Streamlit displays
    renderer.render(spec, result_df) -> plotly Figure
    app.py: charts in a 2-column grid, insights as bullet points,
            transparency report in a collapsible expander

    (Fallback at steps 5-7: chart_engine.generate_charts(df, filename)
     deterministic rules R00-R12, always produces at least 3 charts)
```

---

## Why DuckDB as the Single Source of Truth

After the CSV is loaded, every subsequent operation reads from DuckDB. There is
no parallel pandas path.

**Concrete reasons:**

- **Speed on large files.** DuckDB is column-oriented and runs aggregations
  natively. NYC Airbnb (48,895 rows) profiles and renders in well under 30 seconds.
  An equivalent pandas path would be meaningfully slower for GROUP BY operations.

- **SQL-native cleanup.** Data quality fixes are expressed as SQL expressions
  inside a VIEW definition. Example: a currency column becomes
  `TRY_CAST(regexp_replace(col, '[€$£¥,\s]', '', 'g') AS DOUBLE)`. The
  original data is untouched; the VIEW is the transformation layer.

- **No data duplication.** One connection, one table, one view. The profiler,
  chart engine, and renderer all read from the same `cleaned_data` view.

- **In-process.** DuckDB runs inside the Python process. No separate server,
  no network overhead, no connection pooling.

**What was rejected:**

- Pandas-only: slower for analytics operations; no SQL-native cleanup.
- SQLite: row-oriented, slower for column aggregations.

---

## Why Two Agents, Not One

The two agents have genuinely different inputs and responsibilities.

**Agent 1 -- Chart Planner** receives the *profile* (aggregated statistics, no
raw data). It decides what questions to ask about the dataset and writes the SQL
to answer them. It never sees actual row values.

**Agent 2 -- Insight Writer** receives *actual query results* (the DataFrames
returned after DuckDB executes each spec). It writes 3-5 plain-English sentences
describing what the numbers mean. It does not know how the SQL was generated.

This separation has three benefits:

1. **Security.** Raw user data is never sent to the LLM. The Insight Writer
   receives only aggregated results (top-10 rows per chart at most).

2. **Better outputs.** The Planner is optimized for SQL generation; the Writer
   is optimized for plain language. A single prompt trying to do both produces
   worse SQL and worse prose.

3. **Defensible as agentic.** DuckDB is a real tool used between two LLM steps.
   This is a minimal multi-agent pattern without the overhead of LangGraph.

**What was rejected:** LangGraph, LangChain -- both add framework complexity and
dependencies for a flow with exactly two LLM calls. The custom orchestrator in
`orchestrator/pipeline.py` is 80 lines and does the same job.

---

## The Fallback Engine

`charts/engine.py` implements 13 deterministic chart rules (R00-R12). It runs
without an LLM, without a network connection, and at zero API cost.

**When it triggers:**

- Agent 1 returns zero valid specs after one retry.
- Fewer than 3 LLM specs pass SQL validation after both attempts.
- Any uncaught exception in the LLM path.

**What it produces (priority order, capped at 6 charts by default):**

| Rule | Chart |
|---|---|
| R00 | Summary card (row count, column count, type breakdown) |
| R12 | Missingness bar chart (columns with any nulls) |
| R07 | Records over time (datetime columns) |
| R03 | Bar of counts (low-cardinality categoricals) |
| R08 | Average over time (datetime x numeric) |
| R01/R02 | Histograms (numeric columns, with outlier markers if needed) |
| R04 | Mean by category (numeric x categorical) |
| R05 | Scatter with trend line (numeric pairs with r > 0.4) |
| R06 | Correlation heatmap (r > 0.5 only) |

R09 skips identifier columns. R10 skips columns with more than 40% missing
values. R11 caps high-cardinality categoricals at the top 10.

**Key fix (pandas 3.x compatibility):**
- `to_period("M")` uses `"M"`, not `"ME"` (which is only for `resample()`).
- String dtype check uses `pd.api.types.is_string_dtype()`, not `dtype == object`,
  because DuckDB returns VARCHAR as pandas `StringDtype` in pandas 3.x.

---

## Module Contracts

Each module has a single public entry point. The orchestrator calls these in
sequence; modules do not call each other directly.

| Module | Entry point | Input | Output |
|---|---|---|---|
| `ingestion/loader.py` | `load(csv_path)` | file path (str) | `duckdb.DuckDBPyConnection` |
| `quality/data_quality.py` | `run(con)` | DuckDB connection | `DataQualityResult` (view name, report, profile context) |
| `profiling/profiler.py` | `profile_dataframe(df)` | pandas DataFrame | profile dict |
| `insights/llm_client.py` | `call_llm(system, user, model, max_tokens)` | prompts | LLM response string |
| `agents/chart_planner.py` | `plan_charts(profile, quality_context)` | profile dict, str | `list[ChartSpec]` (empty on full failure) |
| `agents/insight_writer.py` | `write_insights(chart_results)` | `list[tuple[ChartSpec, DataFrame]]` | `list[str]` |
| `charts/engine.py` | `generate_charts(df, filename, max_charts)` | DataFrame, str, int | `list[Figure]` |
| `charts/renderer.py` | `render(spec, result_df)` | `ChartSpec`, DataFrame | `plotly.Figure` |
| `transparency/transparency.py` | `build_report(quality_report)` | quality report dict | `TransparencyReport` |
| `orchestrator/pipeline.py` | `run(csv_path)` | file path (str) | `PipelineResult` |

**`PipelineResult` fields:**

```python
@dataclass
class PipelineResult:
    charts: list[Figure]         # at least 3, always
    insights: list[str]          # plain-English sentences
    transparency: TransparencyReport
    row_count: int
    col_count: int
    used_fallback: bool          # True if LLM path failed
```

---

## Validation Layer

`insights/chart_spec.py` defines `ChartSpec` (Pydantic v2). Validation runs at
three levels:

1. **Field-level:** `title` 3-80 chars, `sql_query` starts with SELECT, etc.
2. **SQL safety:** blocklist for `DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`,
   `CREATE`, `EXEC`, `EXECUTE`, `TRUNCATE`. Query must reference `cleaned_data`.
3. **Cross-field (model_validator):** histogram must have `y_column=None`; scatter
   must have both axes; bar/line must not have `aggregation=NONE`.

On validation failure, the orchestrator sends the error message back to Agent 1
as an additional user message and retries once. If the retry also fails, the spec
is dropped and the fallback engine fills the gap.

---

## Caching

`ui/app.py` wraps `pipeline.run()` with `st.cache_data`, keyed on the file bytes
hash. Re-uploading the same file returns the cached result instantly. Uploading a
new file clears the cache and reruns the pipeline.

The cache is session-local (Streamlit's default). There is no cross-session or
cross-user persistence in this MVP.
