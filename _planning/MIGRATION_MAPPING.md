# Migration Mapping

> Exact mapping from the existing 6 code files to the new modular architecture.
> Specifies what is reused, what is refactored, and what is written from scratch.

---

## 1. Three categories of change

| Category | Meaning |
|---|---|
| **REUSE** | Move file to new location. Update imports only. No logic changes. |
| **REFACTOR** | Split or rename. Extract pieces into separate modules. Logic preserved. |
| **REWRITE** | Logic replaced. May reuse function signatures but internals are new. |
| **NEW** | Did not exist in old codebase. Written from scratch. |

---

## 2. File-by-file mapping

### 2.1 `chart_engine.py` → REUSE (patched — copy from `_existing_code/`) ✅ DONE (95b4eb6)

**Old location:** `/mnt/user-data/outputs/chart_engine.py` (576 lines)
**Canonical source:** `_existing_code/chart_engine.py` (patched during Phase 0)
**New location:** `src/csv_dashboard/charts/engine.py`

**Changes made during Phase 0 validation (2026-05-20):**

1. **`"ME"` → `"M"` in `to_period()`** — pandas 3.x uses `"ME"` for `resample()` but
   `to_period()` still requires `"M"`. Fixed in `chart_records_over_time` and
   `chart_avg_over_time`.

2. **`StringDtype` compatibility** — pandas 3.x + DuckDB returns VARCHAR columns as
   `StringDtype` (dtype `"str"`), not `object`. Replaced `series.dtype == object`
   with `pd.api.types.is_string_dtype(series)` in column classification and
   `_infer_datetime`. Also replaced deprecated `infer_datetime_format=True` with
   `format="mixed", errors="coerce"` + 80% parse-success threshold.

3. **Priority scoring + `max_charts` parameter** — R04 (`n_numeric × n_categorical`)
   and R08 (`n_datetime × n_numeric`) produced combinatorial explosion (66 charts on
   NYC Airbnb). `generate_charts()` now takes `max_charts: int | None = 6` and
   generates charts in priority order: R00 → R12 → R07 → R03 → R08 (top-2) →
   R01/R02 → R04 (top-2 numerics × low-cardinality cats) → R05 (strongest) → R06.
   Pool mode (`max_charts=None`) still returns all charts ordered by priority.
   Also added `MAX_R04_PER_CAT = 2` and `MAX_R08_PER_DT = 2` constants.

**Why:** Phase 0 validated all 5 modules on Titanic (891 rows) and NYC Airbnb
(48,895 rows). These bugs were only found with real data + pandas 3.x. The
canonical patched source is `_existing_code/chart_engine.py`.

**Imports to update inside the file:** None — it has no internal cross-imports
to the project.

---

### 2.2 `data_quality.py` → REUSE ✅ DONE (95b4eb6)

**Old location:** `/mnt/user-data/outputs/data_quality.py` (335 lines)
**New location:** `src/csv_dashboard/quality/data_quality.py`

**Changes:** None. Move as-is.

**Why:** Already DuckDB-first. Already returns the right structure. No reason
to touch it.

---

### 2.3 `profiler.py` → REUSE ✅ DONE (95b4eb6)

**Old location:** `/mnt/user-data/outputs/profiler.py` (215 lines)
**New location:** `src/csv_dashboard/profiling/profiler.py`

**Changes:** None. Move as-is.

**Why:** It is the user-contributed file with hybrid DuckDB+pandas logic.
It already returns the structured profile dict the LLM expects.

---

### 2.4 `chart_spec.py` → REUSE ✅ DONE (95b4eb6)

**Old location:** `/mnt/user-data/outputs/chart_spec.py` (290 lines)
**New location:** `src/csv_dashboard/insights/chart_spec.py`

**Changes:**
- Remove the `import re` and demo `if __name__ == "__main__"` block if present.
- Confirm `FROM CLEANED_DATA` check is the validator (it already is).

**Why:** Pydantic models are stable. The validator logic for SQL is correct.

---

### 2.5 `transparency.py` → REUSE ✅ DONE (95b4eb6)

**Old location:** `/mnt/user-data/outputs/transparency.py` (175 lines)
**New location:** `src/csv_dashboard/transparency/transparency.py`

**Changes:** None. Move as-is.

**Why:** English-only, simple, working. No reason to change.

---

### 2.6 `pipeline.py` → REFACTOR (split into 6 pieces)

**Old location:** `/mnt/user-data/outputs/pipeline.py` (~450 lines)
**New locations:** Split into 6 separate modules.

This is the **only** file that does not survive as a unit. Here is the exact
function-by-function migration:

#### 2.6.1 Functions extracted from old `pipeline.py`

| Old function (in pipeline.py) | Goes to | New location |
|---|---|---|
| `run(csv_path, show, verbose)` | REWRITE | `orchestrator/pipeline.py` (thin) |
| `_profile(...)` | DELETE | replaced by `profile_dataframe` from `profiler.py` |
| `_build_prompt(profile, quality_context)` | REWRITE & RENAME | `insights/prompts.py::build_planner_prompt` |
| `_build_retry_prompt(...)` | REWRITE & RENAME | `insights/prompts.py::build_planner_retry_prompt` |
| `SYSTEM_PROMPT` constant | REWRITE & RENAME | `insights/prompts.py::CHART_PLANNER_SYSTEM` |
| `_ask_llm_with_validation(prompt, verbose)` | REFACTOR | `agents/chart_planner.py::plan_charts` |
| `_execute_and_render(spec, con, df, ...)` | SPLIT | execution → `orchestrator/pipeline.py`<br>rendering → `charts/renderer.py::render` |
| `_render(spec, df)` | REFACTOR & RENAME | `charts/renderer.py::render` |
| `_log(verbose, msg)` | REPLACE | replace with `structlog` calls throughout |
| `Anthropic()` SDK calls | REPLACE | call `insights/llm_client.py::call_llm` instead |

#### 2.6.2 Function signatures: old vs new

**Old (in pipeline.py):**
```python
def _ask_llm_with_validation(
    prompt: str,
    verbose: bool,
) -> tuple[list[ChartSpec] | None, str]:
```

**New (in agents/chart_planner.py):**
```python
def plan_charts(
    profile: dict,
    quality_context: str,
) -> list[ChartSpec]:
    """Returns 3-5 specs. Empty list on failure (caller uses fallback)."""
```

The new signature is cleaner: the agent owns its own prompt building. The
old signature mixed concerns.

---

## 3. What is genuinely NEW (must be written from scratch)

These do not exist in any old file:

### 3.1 `ingestion/loader.py` — NEW

Tiny module. Encapsulates DuckDB CSV loading (currently inline in old pipeline).

Public API:
```python
def load_csv(path: str | Path) -> duckdb.DuckDBPyConnection
class FileLoadError(Exception): ...
```

### 3.2 `insights/llm_client.py` — NEW

Replaces the Anthropic SDK call (`Anthropic().messages.create(...)`) with an
OpenRouter HTTP call via httpx.

Public API:
```python
def call_llm(
    system_prompt: str, user_prompt: str, model: str, max_tokens: int = 2048,
) -> str
class LLMError(Exception): ...
```

### 3.3 `insights/prompts.py` — NEW (contains rewritten content from old pipeline.py)

Contains:
- `CHART_PLANNER_SYSTEM` (rewritten from `SYSTEM_PROMPT`).
- `INSIGHT_WRITER_SYSTEM` (brand new — Insight Writer didn't exist before).
- `build_planner_prompt(profile, quality_context) -> str` (rewritten from `_build_prompt`).
- `build_planner_retry_prompt(original, error, columns) -> str` (rewritten from `_build_retry_prompt`).
- `build_insight_prompt(chart_results) -> str` (brand new).

### 3.4 `agents/chart_planner.py` — REFACTOR from old `_ask_llm_with_validation`

The retry logic and JSON parsing move here, but the LLM call becomes `call_llm`
from the new client.

### 3.5 `agents/insight_writer.py` — NEW

The second agent. Has no equivalent in the old codebase.

Public API:
```python
def write_insights(
    chart_results: list[tuple[ChartSpec, pd.DataFrame]],
) -> list[str]
```

### 3.6 `charts/renderer.py` — REFACTOR from old `_render`

Same logic, extracted to its own module. No behavior change.

### 3.7 `orchestrator/pipeline.py` — REWRITE

The new `pipeline.run` is much thinner: it just calls the modules in order.
The previous 450-line monolith becomes ~120 lines.

### 3.8 `ui/app.py` — NEW

Streamlit UI did not exist in the old code.

### 3.9 `config.py` — NEW

pydantic-settings config. The old code used hard-coded constants.

### 3.10 Everything in `tests/`, `docker/`, `docs/`, `.github/` — NEW

---

## 4. Summary table

| Module | Status | Source | LoC estimate |
|---|---|---|---|
| `config.py` | NEW | — | ~30 |
| `ingestion/loader.py` | NEW | — | ~30 |
| `quality/data_quality.py` | ✅ REUSE DONE | old `data_quality.py` | 398 |
| `profiling/profiler.py` | ✅ REUSE DONE | old `profiler.py` | 290 |
| `insights/llm_client.py` | NEW | — | ~80 |
| `insights/chart_spec.py` | ✅ REUSE DONE | old `chart_spec.py` | 281 |
| `insights/prompts.py` | REFACTOR + NEW | old `pipeline.py` (prompts) + new Insight Writer prompts | ~150 |
| `agents/chart_planner.py` | REFACTOR | old `pipeline.py::_ask_llm_with_validation` | ~80 |
| `agents/insight_writer.py` | NEW | — | ~100 |
| `charts/engine.py` | ✅ REUSE DONE (patched) | `_existing_code/chart_engine.py` | 667 |
| `charts/renderer.py` | REFACTOR | old `pipeline.py::_render` | ~120 |
| `transparency/transparency.py` | ✅ REUSE DONE | old `transparency.py` | 177 |
| `orchestrator/pipeline.py` | REWRITE | old `pipeline.py::run` | ~130 |
| `ui/app.py` | NEW | — | ~200 |
| `tests/*` | NEW | — | ~500 |
| `docker/Dockerfile` | NEW | — | ~20 |
| `docs/*` | NEW | — | ~600 |

**Totals:**
- Reused unchanged: 1,591 lines (5 files).
- Refactored: ~350 lines (3 files).
- New from scratch: ~1,090 lines (10 files).
- Total project size: ~3,000 lines.

---

## 5. Migration order (which to move first)

Following this order minimizes broken imports:

1. **Foundation** — `config.py`, folder structure.
2. **Reuse modules** — move the 5 unchanged files (data_quality, profiler, chart_spec, transparency, chart_engine).
3. **Smoke test** — confirm all imports work.
4. **New leaves** — `ingestion/loader.py`, `insights/llm_client.py`.
5. **New prompts** — `insights/prompts.py`.
6. **Refactored agents** — `agents/chart_planner.py`, `agents/insight_writer.py`.
7. **Extracted renderer** — `charts/renderer.py`.
8. **New orchestrator** — `orchestrator/pipeline.py`.
9. **UI** — `ui/app.py`.

Why this order: each step only depends on what was completed in earlier steps.
No file imports from a module that doesn't exist yet.

---

**End of Migration Mapping. Version 1.0. Date: 2026-05-19.**
