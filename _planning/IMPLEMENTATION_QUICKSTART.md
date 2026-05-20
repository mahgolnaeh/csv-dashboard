# Implementation Session — Quick Start

> Read this **first** before starting the implementation session.

---

## What this session is for

This is the **implementation session** for the CSV Dashboard MVP.
The planning is **complete**. The goal of this session is to write code.

---

## Files you should have from the planning session

You should be uploading or referencing these files at the start:

**Planning documents (read in this order):**

1. **`PROJECT_CONTEXT.md`** — full project context, decisions, and rationale.
2. **`constitution.md`** — governing principles (do not deviate from these).
3. **`spec.md`** — what we're building.
4. **`plan.md`** — how we build it, tech stack, folder structure.
5. **`MIGRATION_MAPPING.md`** — exactly which old files are reused, refactored, or rewritten.
6. **`PROMPT_TEMPLATES.md`** — full system prompts for both agents, ready to copy.
7. **`UX_AND_LOGGING.md`** — Streamlit UI behavior and structured logging strategy.
8. **`tasks.md`** — executable task list.

**Existing code from the previous session** (`/mnt/user-data/outputs/`):

9. `chart_engine.py` — fallback rules engine. **REUSE as-is.**
10. `data_quality.py` — DuckDB cleaning module. **REUSE as-is.**
11. `profiler.py` — profiling module. **REUSE as-is.**
12. `chart_spec.py` — Pydantic models. **REUSE as-is.**
13. `transparency.py` — user-facing transparency. **REUSE as-is.**
14. `pipeline.py` — to be **broken apart**, not reused as a unit. See `MIGRATION_MAPPING.md`.

---

## How to start the implementation session

### Option A — Using Claude Code (recommended)

```bash
# 1. Make a folder
mkdir ~/projects/csv-dashboard
cd ~/projects/csv-dashboard

# 2. Install spec-kit
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git

# 3. Initialize the project with Claude Code integration
specify init . --integration claude --here

# 4. Start Claude Code
claude

# 5. In Claude Code, paste the contents of constitution.md, spec.md, plan.md
#    and tell it to follow them. Then ask it to start with Phase 1.
```

### Option B — Using a fresh Claude.ai chat

1. Open a new chat in Claude.ai.
2. Upload all five planning documents + the six existing code files.
3. Send this exact message as your first message:

> I'm implementing a CSV Dashboard MVP. All the planning is complete and attached:
>
> - PROJECT_CONTEXT.md has the full context.
> - constitution.md has the governing principles.
> - spec.md has the requirements.
> - plan.md has the tech stack and folder structure.
> - MIGRATION_MAPPING.md has the exact reuse/refactor/rewrite plan for the existing code.
> - PROMPT_TEMPLATES.md has the full system prompts for both agents.
> - UX_AND_LOGGING.md has the Streamlit UX and structured logging details.
> - tasks.md has the executable task list.
>
> I've also attached the 6 existing code files from the previous planning session.
>
> Please read all of these in this order: PROJECT_CONTEXT → constitution → spec → plan → MIGRATION_MAPPING → PROMPT_TEMPLATES → UX_AND_LOGGING → tasks.
>
> Then start with **Phase 1, Task T-001** from tasks.md. Work through one task
> at a time, show me the output, and wait for me to confirm before moving on.

---

## Rules for the implementation session

These come from the constitution. The implementer must follow all of them.

1. **English only** in all code, comments, docstrings, and identifiers.
2. **One responsibility per file.** Soft limit: 400 lines.
3. **Type hints on every public function.**
4. **No bare `except:`.** Catch specific exceptions.
5. **No `print()` for runtime info.** Use `structlog`.
6. **The table in SQL is `cleaned_data`, not `data`.**
7. **OpenRouter API key from `.env` only.** Never hard-code or log.
8. **The dashboard always renders.** Fallback engine if LLMs fail.
9. **No Persian text anywhere.** Including UI labels and messages.
10. **Reuse existing code.** Do not rewrite `chart_engine`, `data_quality`,
    `profiler`, `chart_spec`, or `transparency`. Only refactor the orchestrator.

---

## Phase order

Do **not** skip phases or jump ahead. Each phase has a clear "done when" condition.

| Phase | Goal |
|---|---|
| 1 | Foundation: folder structure, dependencies, config, .env |
| 2 | Move existing 5 modules to new structure |
| 3 | Ingestion module (DuckDB loader) |
| 4 | OpenRouter LLM client |
| 5 | Prompts + 2 agents (Chart Planner, Insight Writer) |
| 6 | Renderer (extracted from old pipeline) |
| 7 | Orchestrator (thin pipeline.py) |
| 8 | Streamlit UI |
| 9 | Docker |
| 10 | Documentation (README, ARCHITECTURE, TRADE_OFFS, PRODUCTION_NOTES) |
| 11 | CI |
| 12 | Presentation |

---

## When to stop and ask

The implementer should stop and ask the user when:

- A design decision is ambiguous in `plan.md` or `spec.md`.
- An external dependency would conflict with the constitution.
- A task's "done when" condition is not testable.
- The user's `.env` file is missing the OpenRouter key.

Otherwise, **keep going**.

---

## Smoke test at the end

When all phases are done, run:

```bash
uv run pytest                                              # All tests pass
uv run ruff check .                                        # No lint errors
uv run streamlit run src/csv_dashboard/ui/app.py           # UI launches
docker build -t csv-dashboard -f docker/Dockerfile .       # Docker builds
docker run -p 8501:8501 --env-file .env csv-dashboard      # Docker runs
```

If all five succeed and uploading the Titanic + NYC Airbnb CSVs produces
working dashboards, the MVP is **done**.

---

## What to do if context window runs out mid-implementation

If the new session also fills up before completion:

1. Commit everything to Git.
2. Start a third session.
3. Upload the same planning documents + the **latest code from Git**.
4. Tell the new session which task you were on (from `tasks.md`).
5. Continue from that task.

The planning documents are the source of truth. As long as they're handed off,
no context is lost.

---

**End of Quick Start.**
