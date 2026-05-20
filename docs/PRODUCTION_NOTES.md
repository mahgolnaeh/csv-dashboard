# Production Notes

> Cost, latency, failure modes, security, observability, and scaling.
> This document records what "production thinking from day one" looks like
> for this MVP and what would need to change for a real deployment.

---

## Cost Analysis

### Per-run cost (single CSV upload)

Two LLM calls are made per analysis: Chart Planner and Insight Writer.
Default model: `anthropic/claude-haiku-4-5` via OpenRouter.

| Call | Input tokens (approx) | Output tokens (approx) | Cost at Haiku pricing |
|---|---|---|---|
| Chart Planner | ~1,200 (profile + system prompt) | ~800 (3-5 chart specs JSON) | ~$0.00026 |
| Insight Writer | ~1,500 (query results + system prompt) | ~400 (3-5 insight sentences) | ~$0.00024 |
| **Total** | | | **~$0.0005 per CSV** |

At $0.0005 per run, 2,000 uploads = $1.00. For a demo or internal tool with
low traffic this is negligible.

### Cost levers

- **Haiku vs. Sonnet:** switching to Claude Sonnet increases cost ~10x but
  produces better chart selection on complex schemas.
- **Profile size:** the profiler outputs ~1,000 tokens. Truncating to 500 tokens
  (e.g., top-5 columns only) would halve input cost at the expense of chart quality.
- **Caching:** the same CSV (same SHA256 hash) currently reruns the pipeline in
  each new Streamlit session. A Redis cache keyed on the file hash would eliminate
  repeat LLM costs entirely.
- **Fallback engine:** if the LLM path is disabled, the cost drops to $0.00. The
  fallback engine produces acceptable charts for well-structured CSVs.

---

## Latency Analysis

Measured on a mid-range laptop (M2 MacBook), local DuckDB, OpenRouter API:

| Step | Titanic (891 rows) | NYC Airbnb (48,895 rows) |
|---|---|---|
| DuckDB ingestion | <0.1s | ~0.3s |
| Data quality + VIEW | ~0.2s | ~0.8s |
| Profiling | ~0.1s | ~0.5s |
| Chart Planner LLM call | ~1-3s | ~1-3s (same, profile size is constant) |
| DuckDB executes 3-5 queries | <0.5s | ~1-2s |
| Insight Writer LLM call | ~1-2s | ~1-2s |
| Plotly rendering | <0.2s | ~0.3s |
| **Total** | **~3-7s** | **~5-10s** |

Both are well within the success criteria (<15s for Titanic, <30s for Airbnb).

### Latency levers

- **LLM calls** dominate. Using a local model (Ollama with Llama 3.1) would remove
  network latency but increase hardware requirements and reduce output quality.
- **DuckDB queries** scale well. Even at 500k rows the SQL execution stays under 2s
  for the chart types used here (aggregations, not full table scans).
- **Streaming output:** the Insight Writer call could be streamed (OpenRouter
  supports SSE streaming). This would reduce perceived latency even if total time
  is the same.

---

## Failure Modes and Recovery

### LLM returns malformed JSON

**Detection:** `json.JSONDecodeError` caught in `chart_planner.py`.
**Recovery:** retry once with the error appended to the prompt ("your previous
response was not valid JSON"). On second failure, return empty list.
**Final fallback:** orchestrator detects fewer than 3 valid specs, switches to
`chart_engine.generate_charts()`.

### LLM returns valid JSON but invalid ChartSpec

**Detection:** Pydantic `ValidationError` in `chart_planner.py`.
**Recovery:** same retry-once path with the validation error message.
**Final fallback:** same as above.

### LLM SQL references a non-existent column

**Detection:** DuckDB raises `duckdb.CatalogException` during query execution.
**Recovery:** orchestrator catches the exception, logs it, skips that spec.
**Final fallback:** if fewer than 3 specs succeed, fallback engine supplements.

### OpenRouter API unavailable or rate-limited

**Detection:** `httpx.HTTPStatusError` or `httpx.ConnectError` in `llm_client.py`.
**Recovery:** exception propagates to `chart_planner.py`, returns empty list.
**Final fallback:** chart engine runs immediately, full dashboard renders.

### Unreadable or corrupt CSV

**Detection:** DuckDB raises an exception in `loader.load()`.
**Recovery:** `RuntimeError` with a plain-English message is raised.
**UI handling:** `app.py` catches all exceptions in the pipeline call and
displays a user-readable error with an expander for technical details (collapsed
by default).

### Empty CSV or all-null columns

**Detection:** profiler detects zero usable columns.
**Recovery:** `chart_engine.py` R10 rule skips columns above the missing threshold.
R00 always produces the summary card. UI shows the transparency report explaining
what was dropped.

### Large file (>50MB)

**Detection:** file size check in `app.py` before pipeline call.
**Recovery:** `st.warning` informs the user that processing may be slow.
Streamlit has a default upload limit of 200MB; this is configurable via
`server.maxUploadSize` in Streamlit config.

---

## Security Considerations

### API key handling

- Key is read from `.env` via `pydantic-settings`. It is never logged, printed,
  or echoed in error messages (the `Settings` model treats it as a `SecretStr`).
- The Docker image does not contain the key. It is injected at runtime via
  `--env-file .env` or environment variable.
- No key rotation mechanism exists in this MVP. For production, use a secrets
  manager (AWS Secrets Manager, HashiCorp Vault) and rotate on a schedule.

### SQL injection

All SQL executed by the system is either:
1. Generated by the LLM and validated by the SQL blocklist in `chart_spec.py`
   (blocks `DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`, `CREATE`, `EXEC`,
   `EXECUTE`, `TRUNCATE`).
2. Constructed from sanitized column names (quoted with `"` in DuckDB).

User-provided data (CSV contents) is never interpolated into SQL strings. DuckDB
reads the CSV file directly via `read_csv_auto()`. There is no SQL injection
surface from the upload itself.

### Raw data sent to LLM

The LLM never sees raw user data. Agent 1 (Chart Planner) receives only the
*profile* (aggregated statistics: min, max, mean, cardinality). Agent 2 (Insight
Writer) receives aggregated *query results* (top-10 rows per chart at most).

A CSV containing PII (names, emails, IDs) will not have that data sent to
OpenRouter, because the profile contains only statistics and the results are
GROUP BY aggregations.

### No eval, no exec

No use of Python's `eval()` or `exec()`. SQL is executed by DuckDB, not Python.

### File upload validation

Streamlit accepts any file extension. The loader calls `read_csv_auto()`, which
will raise a DuckDB error on non-CSV content. This error is caught and shown as a
user-readable message. There is no path traversal risk because the file is written
to a temp path by Streamlit before being passed to the loader.

---

## Observability

### Logging

All pipeline steps log at INFO level using `structlog` with JSON output. Each log
event includes the step name, timing, and relevant metadata.

Example log events:
```json
{"event": "ingestion_complete", "row_count": 48895, "col_count": 16, "elapsed_s": 0.31}
{"event": "data_quality_complete", "issues": 3, "dropped_cols": 1, "elapsed_s": 0.82}
{"event": "chart_planner_success", "n_specs": 4, "attempt": 1, "elapsed_s": 2.14}
{"event": "chart_planner_fallback", "reason": "validation_error", "elapsed_s": 3.01}
{"event": "insight_writer_success", "n_insights": 4, "elapsed_s": 1.87}
{"event": "pipeline_complete", "used_fallback": false, "total_elapsed_s": 5.9}
```

### What is not yet instrumented

- Per-chart render time.
- LLM token counts (OpenRouter returns these in the response; they are not
  currently stored).
- User-facing events (upload count, fallback rate, error rate).

For a production deployment, these would feed into a dashboard (Grafana, Datadog,
or a simple Streamlit admin page) to track cost, latency, and fallback rate over
time.

---

## Scaling Path

This is a single-process, single-user Streamlit app. What would need to change
for multi-user or higher traffic?

### Step 1: Result caching (10-100 users, same datasets)

Add a shared cache (Redis or DiskCache) keyed on the file's SHA256 hash. Users
uploading the same CSV (e.g., a shared company dataset) get instant results.
Estimated effort: 1 day.

### Step 2: Worker pool (10-100 concurrent users)

The pipeline is CPU/IO-bound (DuckDB + HTTP). Replace the Streamlit inline call
with a task queue (Celery + Redis, or FastAPI + asyncio). Each upload queues a job;
the UI polls for results. Streamlit's session model does not support this natively;
this step would require moving to a FastAPI backend with a Streamlit or React
frontend. Estimated effort: 1 week.

### Step 3: DuckDB -> MotherDuck or a shared DB (persistent storage)

The current DuckDB instance is in-memory and session-local. For a multi-user
deployment with persistent results, MotherDuck (DuckDB-as-a-service) or Postgres
(with DuckDB's Postgres scanner for analytics) would be the next step.

### Step 4: LLM cost controls

At scale, add a rate limiter per user/IP, a per-run cost cap, and model tiering
(Haiku for free tier, Sonnet for paid). Budget alerts via OpenRouter's usage API.

### Step 5: Cloud deployment

The Dockerfile runs on any container platform. Minimal path: Cloud Run (GCP) or
App Runner (AWS) with an environment variable for the API key. Add a CDN for
static assets and a load balancer for multiple instances. Estimated effort: 2 days
(if the worker pool step is already done).

---

## What This MVP Deliberately Does Not Handle

- Multi-user sessions with isolation guarantees.
- Files larger than ~200MB (Streamlit upload limit; DuckDB would handle it but
  the UI would time out).
- Streaming CSVs or append-only data sources.
- Non-UTF-8 encoded files (DuckDB auto-detects most encodings, but not all).
- CSVs with more than ~50 columns (the profile would exceed the LLM context;
  a column sampling step would be needed).

These are documented here so that the next engineer knows exactly where the
boundaries are.
