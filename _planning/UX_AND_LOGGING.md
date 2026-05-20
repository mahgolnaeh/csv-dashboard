# UX and Logging Details

> Detailed specifications for Streamlit UI behavior and structured logging.

---

## 1. Streamlit UI

### 1.1 Page layout

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   📊 CSV Dashboard                                          │
│   Upload a CSV. Get insights. No setup needed.              │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │   Drag and drop your CSV here, or click to browse   │   │
│   │   Max 100 MB. Any column structure.                 │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

After upload, the page extends downward with the result sections.

### 1.2 Section order (top to bottom after upload)

1. **Loading status** (visible only during processing)
2. **Dataset summary** (always visible after processing)
3. **Data preparation** (collapsible, collapsed by default)
4. **Key insights** (always visible)
5. **Charts** (grid, 2 per row on desktop, 1 per row on mobile)
6. **Errors** (only if non-empty)

### 1.3 Loading status — progressive updates

Streamlit reruns top-to-bottom on every interaction. Use `st.status()` (the
collapsible status block) to show progress:

```python
with st.status("Analyzing your data...", expanded=True) as status:
    st.write("📂 Loading CSV...")
    con = load_csv(path)

    st.write("🧹 Checking data quality...")
    dq = run_quality(con)

    st.write("📊 Profiling columns...")
    df = con.execute('SELECT * FROM "cleaned_data"').df()
    profile = profile_dataframe(df)

    st.write("🤖 Asking AI to design charts...")
    specs = plan_charts(profile, dq["llm_context"])

    st.write(f"📈 Generating {len(specs)} charts...")
    # ... execute and render

    st.write("💡 Writing insights...")
    insights = write_insights(chart_results)

    status.update(label="Done!", state="complete", expanded=False)
```

Why this matters: a 30-second wait on a black screen feels broken. Even rough
progress messages turn a long wait into a guided process.

### 1.4 Dataset summary card

```python
col1, col2, col3 = st.columns(3)
col1.metric("Rows", f"{profile['row_count']:,}")
col2.metric("Columns", profile['column_count'])
col3.metric("Quality issues",
            sum(1 for r in result.transparency['sentences']))
```

Compact, scannable, no jargon.

### 1.5 Data preparation section

Use `st.expander` collapsed by default:

```python
n_changes = len(result.transparency['sentences'])
if n_changes > 0:
    label = f"📋 What we did to prepare your data ({n_changes} changes)"
    with st.expander(label, expanded=False):
        transparency.show_in_streamlit(dq_quality_report)
else:
    st.info("Your data was clean — no preparation needed.")
```

### 1.6 Insights section

```python
st.markdown("### Key insights")
if result.insights:
    for insight in result.insights:
        st.markdown(f"- {insight}")
else:
    st.caption("No AI-generated insights available — showing charts only.")
```

### 1.7 Charts grid

```python
st.markdown("### Charts")

# Source badge: LLM vs fallback
n_llm = sum(1 for c in result.charts if c.source == "llm")
n_fallback = sum(1 for c in result.charts if c.source == "fallback")
if n_fallback > 0 and n_llm == 0:
    st.caption("Using simplified chart generation (AI service unavailable).")
elif n_fallback > 0:
    st.caption(f"{n_llm} AI-designed charts + {n_fallback} standard charts.")

# 2-column grid
for i in range(0, len(result.charts), 2):
    col1, col2 = st.columns(2)
    cols = [col1, col2]
    for j, chart in enumerate(result.charts[i:i+2]):
        with cols[j]:
            st.plotly_chart(chart.figure, use_container_width=True)
            if chart.explanation:
                st.caption(chart.explanation)
```

### 1.8 Error banner

```python
if result.errors:
    with st.expander(f"⚠️ {len(result.errors)} warning(s)", expanded=False):
        for err in result.errors:
            st.warning(err)
```

### 1.9 Caching

```python
@st.cache_data(show_spinner=False)
def cached_run(file_bytes: bytes, filename: str) -> PipelineResult:
    """Cache by file content hash. Re-uploads of the same file skip processing."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        return pipeline.run(tmp.name)
```

Why bytes, not path: Streamlit's cache key is the function arguments. The bytes
fingerprint changes only when the file content changes. A path-based key would
miss content updates if the temp file path stayed the same.

### 1.10 File size warning

```python
uploaded = st.file_uploader("Upload CSV", type=["csv"])
if uploaded:
    size_mb = uploaded.size / (1024 * 1024)
    if size_mb > 50:
        st.info(f"File is {size_mb:.0f} MB. Analysis may take up to a minute.")
    if size_mb > 100:
        st.error("File exceeds 100 MB limit.")
        st.stop()
    # ... proceed
```

### 1.11 Fallback charts visual distinction

Fallback charts come from the rule engine. They are reliable but less tailored.
A small badge under each chart distinguishes them:

```python
for chart in charts:
    with col:
        st.plotly_chart(chart.figure, use_container_width=True)
        if chart.source == "llm":
            st.caption(f"💡 {chart.explanation}")
        else:
            st.caption(f"📐 Standard chart")
```

Why: honesty. The user sees what came from AI reasoning vs deterministic rules.

### 1.12 Error states

| Failure | UI behavior |
|---|---|
| File too large | Red banner, stop processing |
| File unreadable | Red banner with the FileLoadError message |
| All columns dropped | Red banner: "No usable columns found in this file" |
| LLM completely unavailable | Yellow banner: "Using simplified chart generation" |
| Some charts fail to render | Show successful ones; warning in expander |
| Crash during processing | Catch in main `try/except`; show "Something went wrong" + error in expander |

Never show a Python traceback to the user. Log it internally.

---

## 2. Logging Strategy

### 2.1 Why structlog

- Structured JSON output → easy to grep, ship to a log aggregator later.
- Context binding → log entries automatically carry pipeline-step info.
- No format-string vulnerabilities.

### 2.2 Setup

```python
# src/csv_dashboard/logging_setup.py
import logging
import structlog
import sys

def setup_logging(level: str = "INFO"):
    """Configure structlog to emit JSON logs to stdout."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        cache_logger_on_first_use=True,
    )

log = structlog.get_logger()
```

Called once at app startup from `ui/app.py` and any test fixture.

### 2.3 What to log

| Event | Log level | Fields |
|---|---|---|
| Pipeline started | INFO | csv_path, file_size_bytes |
| CSV loaded | INFO | row_count, column_count |
| Data quality complete | INFO | dropped_cols, n_warnings, n_fixes |
| Profiling complete | INFO | semantic_type_counts |
| LLM call started | DEBUG | model, system_prompt_chars, user_prompt_chars |
| LLM call completed | INFO | model, duration_ms, input_tokens, output_tokens |
| LLM call failed | ERROR | model, error, attempt_num |
| Pydantic validation failed | WARNING | error, will_retry |
| SQL execution failed | WARNING | spec_title, error, will_retry |
| Fallback engine triggered | INFO | reason, n_specs_received |
| Chart rendered | DEBUG | spec_title, chart_type |
| Insights generated | INFO | n_insights, duration_ms |
| Pipeline completed | INFO | total_duration_ms, n_charts, n_insights, n_errors |

### 2.4 What NOT to log

- The OpenRouter API key — ever.
- Raw CSV file contents.
- Full LLM responses in production (only in DEBUG mode).
- PII or anything that might be PII (column values, sample rows).
- Stack traces for handled errors (use `log.warning` not `log.error`).

### 2.5 Context binding for pipeline steps

```python
import structlog

log = structlog.get_logger()

def run(csv_path: str) -> PipelineResult:
    bound = log.bind(csv_path=csv_path, pipeline_id=uuid.uuid4().hex[:8])
    bound.info("pipeline_started")

    try:
        con = load_csv(csv_path)
        bound.info("csv_loaded", row_count=..., column_count=...)
        # ...
        bound.info("pipeline_completed", duration_ms=..., n_charts=...)
    except Exception as e:
        bound.exception("pipeline_failed", error=str(e))
        raise
```

Every log line in this pipeline run carries `csv_path` and `pipeline_id`,
making it trivial to follow a single request through the logs.

### 2.6 Log levels by environment

| Environment | Level |
|---|---|
| Local development | DEBUG |
| CI / tests | WARNING (less noise) |
| Docker / "production" demo | INFO |

Controlled via `LOG_LEVEL` env var (read by `config.py`).

### 2.7 Example log output

```json
{"event": "pipeline_started", "csv_path": "/tmp/titanic.csv", "pipeline_id": "a3f8b2c1", "level": "info", "timestamp": "2026-05-19T14:23:01.234Z"}
{"event": "csv_loaded", "csv_path": "/tmp/titanic.csv", "pipeline_id": "a3f8b2c1", "row_count": 891, "column_count": 12, "level": "info", "timestamp": "2026-05-19T14:23:01.298Z"}
{"event": "llm_call_completed", "csv_path": "/tmp/titanic.csv", "pipeline_id": "a3f8b2c1", "model": "anthropic/claude-haiku-4.5", "duration_ms": 2103, "input_tokens": 1842, "output_tokens": 612, "level": "info", "timestamp": "2026-05-19T14:23:03.401Z"}
{"event": "pipeline_completed", "csv_path": "/tmp/titanic.csv", "pipeline_id": "a3f8b2c1", "total_duration_ms": 8421, "n_charts": 4, "n_insights": 3, "n_errors": 0, "level": "info", "timestamp": "2026-05-19T14:23:09.655Z"}
```

This is straightforward to grep, analyze, and (in production) ship to
DataDog/Sentry/CloudWatch.

---

## 3. Why this matters for the interview

**Telekom asks about observability.** Without structured logging, the answer
is hand-wavy. With it, the answer is concrete:

> "Every pipeline step emits a structured JSON log line with the pipeline ID,
> step name, duration, and outcome. We use structlog with context binding so
> every log line in a single run carries the same pipeline ID. To ship to
> production, we'd plug in a Logstash or Vector forwarder — the JSON output
> is already in the right shape."

**Telekom asks about UX.** The progressive status, the transparency report,
the source badges (LLM vs fallback), the file size warnings — these are all
small details that show user thinking, not just feature thinking.

---

**End of UX and Logging Details. Version 1.0. Date: 2026-05-19.**
