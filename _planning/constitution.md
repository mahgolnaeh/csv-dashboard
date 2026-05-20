# Constitution — CSV Dashboard MVP

> Foundational principles for this project.
> All specifications, plans, and tasks must adhere to these principles.
> When in doubt, this document wins.

---

## I. Purpose

Build an MVP that transforms any CSV file into a **dashboard with insights**
for a **non-technical user**. The system must work across domains, schemas,
and dataset sizes (hundreds to tens of thousands of rows) without prior knowledge
of the data.

This is a case study for the Deutsche Telekom AI & Digital Innovation internship.
**Engineering judgment is evaluated, not feature count.**

---

## II. Non-Negotiable Principles

### 1. The non-technical user is the audience

Every output — charts, insights, error messages, transparency reports —
must be readable by someone with **no statistics, no programming, and no
data engineering background.**

- No jargon. No "outliers", "skewness", "IQR" in user-facing text.
- Every chart has a plain-English explanation as a subtitle.
- Every data fix is reported in plain English ("Currency symbols removed,
  values converted to numbers"), not technical detail ("regexp_replace + TRY_CAST").
- Error messages name the cause and what the user can do.

### 2. Transparency is mandatory

If we change the data, the user must know.
If we drop a column, the user must know.
If we detect something suspicious, the user must know.

The transparency report is not optional — it is part of building trust.

### 3. The system must never crash on the user

Every step must have a fallback or graceful failure.
- LLM call fails → retry once → use deterministic fallback engine.
- SQL fails → retry LLM with error message → use fallback.
- File unreadable → clear error message, no stack trace.
- Empty dataset → message explaining what's needed.

**The dashboard always renders, even when everything LLM fails.**

### 4. DuckDB is the single source of truth

There is exactly **one** data layer. After ingestion, all reads,
profiling, cleaning, and chart queries go through DuckDB.
No parallel pandas paths. No re-loading from disk.

Data cleaning is a **SQL VIEW** on top of the raw table, not a mutation.

### 5. The LLM is a tool, not a magician

LLM output is always validated.
- Pydantic models enforce structure and types.
- SQL validators block dangerous queries (`DROP`, `DELETE`, etc.).
- Cross-field rules catch logical errors (histogram with y_column).
- LLM never sees raw data — only aggregated profiles.

If the LLM fails, the deterministic engine takes over.

### 6. Modularity over monolith

Every module has a **single responsibility** and a **clear contract**.
- One file, one job.
- Each file under 400 lines (target).
- No file depends on internal details of another — only on its public interface.
- The orchestrator wires modules; modules don't call each other directly.

This makes the system testable, debuggable, and reusable.

### 7. Production thinking from day one

Even as an MVP, decisions consider:
- **Cost** — LLM calls are minimized; cheap models by default.
- **Latency** — heavy work happens in DuckDB; LLM calls only when needed.
- **Failure modes** — every external dependency has a fallback.
- **Observability** — structured logs at each pipeline step.
- **Security** — no `eval`, no raw user data sent to LLM, validated SQL.
- **Reproducibility** — Dockerfile, pinned dependencies, deterministic fallback.

### 8. Honest trade-offs

What we don't build is as important as what we build.
- Each rejected option has a recorded reason.
- "We chose X over Y because Z" is the standard.
- The presentation explicitly lists what was cut and what would come next.

---

## III. Technology Principles

### Choice criteria

A tool is chosen if it satisfies, in order:
1. **Reliability** — proven, well-maintained, low risk of failure.
2. **Fit** — solves this specific problem without over-engineering.
3. **Cost** — free or minimal cost for MVP and reasonable at scale.
4. **Defensibility** — we can explain why this tool over alternatives in 30 seconds.

### Confirmed choices (with rationale)

| Layer | Choice | Why |
|---|---|---|
| Data engine | DuckDB | SQL-native, fast on 48k rows, in-process, free |
| LLM gateway | OpenRouter | One API, multiple models, easy fallback between models |
| Validation | Pydantic v2 | Type + cross-field validation, clean error messages |
| Visualization | Plotly | Interactive, professional, works in Streamlit |
| UI | Streamlit | Fast MVP for non-technical users |
| Config | pydantic-settings | Typed config from .env, no string-parsing |
| Packaging | uv + pyproject.toml | Fast, reproducible, modern |
| Container | Docker | Reproducible runs, demo-friendly |

### Rejected choices (with reason)

| Rejected | Why not |
|---|---|
| LangGraph / LangChain | Overkill for 2 agents; adds complexity, dependencies |
| Anthropic SDK directly | Vendor lock-in; OpenRouter lets us swap models |
| Pandas-only data layer | Slower on large files; mixing with DuckDB creates two paths |
| SQLite | Slower for analytics; DuckDB is column-oriented |
| Gradio | Less suited for dashboard layouts |
| FastAPI + custom HTML | Too much frontend work for an MVP |
| Cloud deployment | Out of scope; Dockerfile is enough for demo |
| ORM (SQLAlchemy) | No multi-table joins in this MVP |
| Manual JSON Schema | Pydantic is more Pythonic and gives better errors |

---

## IV. Quality Standards

### Code

- Type hints on every function signature.
- Docstrings on every public function (what it does, inputs, outputs, errors).
- No mutable default arguments.
- No bare `except:` clauses — always catch specific exceptions.
- No `print()` for runtime info — use the `logging` module.
- One responsibility per file.
- Tests for every module that has logic (not just glue).

### Naming

- Files: `snake_case.py`.
- Modules: short, descriptive, no abbreviations (`profiler.py`, not `prf.py`).
- Functions: verbs (`run`, `clean`, `profile`, `render`).
- Classes: nouns, `PascalCase` (`ChartSpec`, not `chart_spec`).
- Constants: `UPPER_SNAKE_CASE`.

### Language

- **All code, comments, docstrings, and identifiers in English.**
- No Persian, no Farsi, no other languages in the source.
- User-facing strings also in English (UI is for an international audience).

### Testing

- Each new module has at least one test.
- Pipeline has an end-to-end test with a synthetic CSV.
- LLM calls are mocked in tests — never hit the real API in CI.
- Tests run in <30 seconds total.

### Documentation

- Every module has a top-of-file docstring explaining its role.
- The README explains: what it does, how to run it (local + Docker), how to test, what's missing.
- The `docs/` folder has architecture and trade-off documents for the presentation.

---

## V. Governance

### How decisions are made

1. **Spec first.** A change is proposed in `spec.md` or a new spec file.
2. **Plan second.** The technical impact is added to `plan.md`.
3. **Tasks third.** The work is broken down in `tasks.md`.
4. **Implement last.** No code is written without a corresponding task.

### When this constitution conflicts with a request

The constitution wins. Either:
- The request is refined to comply, or
- The constitution is amended (a separate, explicit decision).

Never silently break a principle.

### What triggers a constitution update

- A trade-off changes (e.g., we add a real cloud deployment → update Section III).
- A user-facing principle changes (e.g., we add multi-language UI → update Section II.1).
- A quality standard changes (e.g., we adopt mypy → update Section IV).

Document every amendment with a date and a reason.

---

## VI. Out of Scope (for MVP)

These are explicitly **not** in scope and will not be built:

- Multi-user authentication, sharing, or permissions.
- Live data sources (databases, APIs, streaming).
- Persistence beyond a single session (save/load dashboards).
- Multi-file joins.
- Custom chart types beyond Plotly's built-ins.
- Mobile-responsive UI tweaks.
- Cloud deployment automation.
- Multi-language UI.
- A REST API (only Streamlit UI).
- Real-time updates.
- User accounts or settings.

These appear in the "what's next" section of the presentation,
not in the codebase.

---

**End of Constitution. Version 1.0. Date: 2026-05-19.**
