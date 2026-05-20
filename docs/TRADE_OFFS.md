# Trade-offs

> Every decision is a trade-off. This document records what we chose, what we
> rejected, and what we would build next.

---

## What We Chose and Why

### DuckDB over pandas-only

Pandas works fine for 891 rows. At 48,895 rows with multiple GROUP BY operations
it is noticeably slower and the code is less readable than SQL. DuckDB gives us
column-oriented analytics, native SQL expressions for data cleaning, and an
in-process engine with no server to manage.

The rejected alternative (loading into pandas, running `.groupby().agg()`, writing
results back) would have created two data paths -- one for cleaning, one for
querying -- with the associated risk of subtle inconsistencies.

### OpenRouter over direct Anthropic SDK

OpenRouter is a single API that proxies Anthropic, OpenAI, Google, and others. If
Claude Haiku is rate-limited or unavailable, we can switch models by changing one
string in `.env`. With the Anthropic SDK we are locked to one provider.

The rejected alternative was using `anthropic` directly, which would require
rewriting the client if we wanted to try GPT-4o-mini or Gemini Flash for cost
comparison.

### Custom two-agent orchestrator over LangGraph

Two LLM calls with a DuckDB execution step between them. The orchestrator that
wires them is 80 lines of plain Python in `orchestrator/pipeline.py`. LangGraph
would add a framework dependency, a new abstraction layer, and significant
additional complexity for identical functionality.

The rule: if the agent graph fits in a linear sequence of function calls, a
framework adds overhead without adding capability.

### Deterministic fallback over LLM retry with a different prompt

When the LLM fails (bad JSON, failed SQL, network error), the fallback is
`chart_engine.py` -- 12 deterministic rules that always produce at least 3 charts.
The alternative (retrying with a rephrased prompt, or trying a second model) adds
latency, adds cost, and still may not succeed.

The fallback is zero-cost, zero-latency, and predictable. It also makes a stronger
engineering argument: "the system works with or without the LLM."

### Pydantic v2 for validation over manual JSON checks

Chart specs returned by the LLM are validated by a Pydantic model with field
validators, cross-field rules, and a SQL safety blocklist. The alternative (manual
`isinstance` checks and string comparisons) produces worse error messages and is
harder to extend.

### Streamlit over Gradio or FastAPI + HTML

Streamlit is optimized for data apps with charts. It handles file upload, layout,
expanders, and Plotly figures out of the box. Gradio is better suited for ML model
demos. FastAPI + HTML would require building a frontend, which is out of scope for
a three-week MVP.

---

## What We Deliberately Cut

These features are not in the codebase. Each was a conscious decision.

### Multi-user authentication and sharing

Not part of the assignment. Adding auth (sessions, tokens, user accounts) would
double the engineering surface area without adding anything to the demo.

### Persistence beyond a single session

Dashboards are generated on demand and not saved. A database layer for storing
results, user preferences, or previous analyses was evaluated and cut. The upload
workflow is fast enough that regeneration on revisit is acceptable for an MVP demo.

### Multi-file joins

The assignment is "any CSV." One file at a time is the correct scope. Supporting
joins would require a schema matching step and significantly more prompt engineering.

### Live data sources (database connections, APIs, streaming)

CSV is the explicit input format for this case study. Connecting to PostgreSQL,
BigQuery, or Kafka is a different product category.

### Cloud deployment automation

A Dockerfile is sufficient for the demo. A Terraform/Pulumi stack or a Heroku
deployment would add infrastructure complexity with no evaluation benefit.

### LangGraph or LangChain

Evaluated and rejected. Two LLM calls in sequence do not justify a framework.
"We looked at LangGraph but the orchestrator complexity was not justified for two
agents" is a stronger answer than "we used LangGraph because it's popular."

### ORM (SQLAlchemy or similar)

No relational schema to manage. DuckDB is queried directly via its Python API.
An ORM would add an abstraction layer between us and the SQL we are already
writing explicitly.

### Boxplot chart type

The original chart engine included boxplots for numeric distributions. Boxplots
use statistical vocabulary (median, quartile, whisker) that is not accessible to
non-technical users. Replaced with histograms plus a plain-language annotation.
Constitution Section II.1: no jargon in user-facing output.

### Mobile-responsive UI tweaks

Streamlit's default layout works on desktop. A mobile breakpoint would require
custom CSS and testing across viewports. Not in scope for a 3-week MVP.

---

## What We Would Build Next

These are ordered by the impact they would have on the real-world usefulness of
the system.

### 1. Result caching with content-hash keying (1-2 days)

The current `st.cache_data` is session-local. Uploading the same file in a new
browser tab reruns the pipeline. A Redis or SQLite cache keyed on the file's SHA256
hash would skip the LLM calls entirely for repeat uploads. At ~$0.001 per run, this
adds up quickly for a shared deployment.

### 2. User feedback loop (3-5 days)

Thumbs up / thumbs down per chart. Store (profile, chart_spec, feedback) triples.
Use negative feedback to add examples to the system prompt ("avoid histograms for
columns with fewer than 5 unique values"). This would improve Chart Planner output
over time without retraining a model.

### 3. Multi-page / multi-file support (1 week)

Allow the user to upload two CSVs and join them on a common key. Requires a schema
matching step (detect join candidates by name similarity and type overlap) and a
more complex prompt that describes two tables instead of one.

### 4. Dashboard persistence and sharing (1 week)

Save `PipelineResult` to a database, generate a shareable URL. Requires a user
model (even a simple anonymous token), a storage layer, and a retrieval endpoint.
Streamlit Community Cloud can host this without a separate backend.

### 5. Model selection and cost controls (2-3 days)

Let the user choose "fast/cheap" vs. "thorough/expensive" mode. Fast mode uses
Haiku; thorough mode uses Claude Sonnet or GPT-4o. Add a per-run cost estimate
to the UI ("estimated cost: $0.002").

### 6. Streaming insights (2-3 days)

Stream the Insight Writer's output token-by-token using OpenRouter's streaming API.
The user sees the insights appear in real time instead of waiting for the full
response. Improves perceived latency, especially for larger datasets.

### 7. Scheduled reports (1 week)

Connect to a live data source (database, API endpoint, Google Sheet) and run the
pipeline on a schedule. Send the dashboard as a PDF or HTML email. Requires a task
queue (Celery or a simple cron job) and an email integration.

### 8. Custom chart requests (2-3 days)

Add a text input below the charts: "Show me X by Y." Parse this as a natural-language
query, run it through the Chart Planner with the existing column context, and append
the result to the dashboard. This makes the tool interactive, not just reactive.

---

## The One Thing We Would Do Differently

The data quality module (`data_quality.py`) and the profiler (`profiler.py`) were
inherited from an earlier prototype and adapted rather than rewritten. They work,
but their test coverage is sparse and their interface contracts are implicit (return
dicts rather than typed dataclasses). In a production codebase, both would be
rewritten with explicit return types, comprehensive unit tests, and clearer
separation between detection and reporting.
