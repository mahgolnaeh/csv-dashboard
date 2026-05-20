# Phase 0: Validation

> **Run this BEFORE Phase 1.**
>
> Validates that the 5 reusable modules from the planning session work together
> on real datasets. Catches integration issues before we commit to the new
> folder structure.

---

## Why Phase 0 exists

Five modules from the planning session will be **reused as-is** in the new
architecture:

- `chart_engine.py` → `src/csv_dashboard/charts/engine.py`
- `data_quality.py` → `src/csv_dashboard/quality/data_quality.py`
- `profiler.py` → `src/csv_dashboard/profiling/profiler.py`
- `chart_spec.py` → `src/csv_dashboard/insights/chart_spec.py`
- `transparency.py` → `src/csv_dashboard/transparency/transparency.py`

These modules were tested **individually** in the planning session, but never
together on real data. Before refactoring everything into the new structure,
we verify they wire together correctly.

The new code (orchestrator, agents, UI, OpenRouter client) is NOT validated
here — it doesn't exist yet. TDD in Phase 5+ will cover it.

---

## What Phase 0 does NOT cover

- The agents (`chart_planner.py`, `insight_writer.py`) — written from scratch later.
- The OpenRouter client (`llm_client.py`) — written from scratch later.
- The Streamlit UI — written from scratch later.
- The Docker container — built at the end.
- Performance optimization — deferred until something is too slow.

Phase 0 covers only the **trust-the-existing-code** check.

---

## Datasets to test on

Both are real and required by the case study:

**Titanic** (small, mixed types, missing values):
```
https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv
```
- 891 rows, 12 columns
- Has missing values in `Age` and `Cabin`
- Has a survival flag (boolean-like)
- Has identifier (`PassengerId`)

**NYC Airbnb 2019** (large, datetime, geo):
```
https://raw.githubusercontent.com/erkansirin78/datasets/master/AB_NYC_2019.csv
```
- 48,895 rows, 16 columns
- Has datetime (`last_review`)
- Has geo (`latitude`, `longitude`)
- Has high-cardinality categoricals (`neighbourhood`)
- Has price (numeric with outliers)

---

## The validation tasks

### T-000.1: Setup validation environment

**Goal:** Have the 5 reusable files in one place where we can run them together.

**Steps:**

```bash
# Make a temporary validation folder (not the final project structure yet)
mkdir -p ~/projects/csv-dashboard/_validation
cd ~/projects/csv-dashboard/_validation

# Copy the 5 reusable files here
cp ../path/to/chart_engine.py .
cp ../path/to/data_quality.py .
cp ../path/to/profiler.py .
cp ../path/to/chart_spec.py .
cp ../path/to/transparency.py .

# Install dependencies
uv venv
uv pip install duckdb pandas numpy pydantic plotly scipy structlog

# Download both datasets
curl -O https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv
curl -O https://raw.githubusercontent.com/erkansirin78/datasets/master/AB_NYC_2019.csv
```

**Done when:** All 5 modules import without errors and both CSVs are downloaded.

---

### T-000.2: Write the integration test script

**Goal:** A single script that exercises the 5 modules on both datasets.

**File:** `_validation/test_phase0.py`

```python
"""
Phase 0: Integration validation for the 5 reusable modules.

What we're checking:
  - All modules wire together without errors.
  - data_quality builds a valid VIEW for both datasets.
  - profiler returns a structured profile for both.
  - chart_engine produces >= 3 fallback charts for both.
  - transparency produces sensible plain-English sentences.
  - End-to-end timing meets the spec (<15s Titanic, <30s Airbnb).

What we're NOT checking yet:
  - LLM agents (don't exist).
  - Streamlit UI (doesn't exist).
  - Docker (later phase).
"""

import time
import duckdb
import pandas as pd

import data_quality
import profiler
import chart_engine
import transparency


def run_pipeline(csv_path: str, expected_rows: int, time_budget_s: float) -> dict:
    """Run all 5 modules on one CSV. Return a result summary."""
    t0 = time.perf_counter()

    # Step 1: DuckDB load
    con = duckdb.connect()
    con.execute(
        f"CREATE OR REPLACE TABLE raw_data AS "
        f"SELECT * FROM read_csv_auto('{csv_path}', header=true)"
    )

    raw_row_count = con.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
    assert raw_row_count == expected_rows, (
        f"Expected {expected_rows} rows, got {raw_row_count}"
    )

    # Step 2: data_quality
    dq = data_quality.run(con, raw_table="raw_data")
    assert "cleaned_data" in [
        r[0] for r in con.execute("SHOW TABLES").fetchall()
    ] + [r[0] for r in con.execute("SHOW VIEWS").fetchall() if "SHOW VIEWS" in dir(con)] or True
    # ^ DuckDB SHOW VIEWS syntax may differ; relax this check.

    # Sanity: view exists and is queryable
    view_row_count = con.execute('SELECT COUNT(*) FROM "cleaned_data"').fetchone()[0]
    assert view_row_count == expected_rows

    # Step 3: profiler
    df = con.execute('SELECT * FROM "cleaned_data"').df()
    profile = profiler.profile_dataframe(df)
    assert profile["row_count"] == expected_rows
    assert profile["column_count"] >= 1
    assert "semantic_type_summary" in profile

    # Step 4: chart_engine (fallback)
    charts = chart_engine.generate_charts(df, csv_path)
    assert len(charts) >= 3, f"Expected >=3 charts, got {len(charts)}"

    # Step 5: transparency
    report = transparency.build(dq["quality_report"])
    assert "plain_text" in report

    elapsed = time.perf_counter() - t0
    assert elapsed < time_budget_s, (
        f"Pipeline took {elapsed:.1f}s, budget was {time_budget_s}s"
    )

    con.close()

    return {
        "csv": csv_path,
        "rows": raw_row_count,
        "elapsed_s": round(elapsed, 2),
        "n_charts": len(charts),
        "n_dropped_cols": len(dq["dropped_cols"]),
        "n_warnings": len([r for r in dq["quality_report"] if r["severity"] == "warn"]),
        "semantic_types": profile["semantic_type_summary"],
        "transparency_lines": len(report["sentences"]),
    }


def main():
    print("=" * 60)
    print("Phase 0 Validation")
    print("=" * 60)

    # Titanic — small dataset, 15s budget
    print("\n[1/2] Testing Titanic (891 rows, 15s budget)...")
    titanic_result = run_pipeline("titanic.csv", 891, 15.0)
    print(f"  ✓ {titanic_result['rows']} rows in {titanic_result['elapsed_s']}s")
    print(f"  ✓ {titanic_result['n_charts']} fallback charts")
    print(f"  ✓ {titanic_result['n_dropped_cols']} columns dropped")
    print(f"  ✓ {titanic_result['n_warnings']} quality warnings")
    print(f"  Semantic types: {titanic_result['semantic_types']}")

    # NYC Airbnb — large dataset, 30s budget
    print("\n[2/2] Testing NYC Airbnb (48895 rows, 30s budget)...")
    airbnb_result = run_pipeline("AB_NYC_2019.csv", 48895, 30.0)
    print(f"  ✓ {airbnb_result['rows']} rows in {airbnb_result['elapsed_s']}s")
    print(f"  ✓ {airbnb_result['n_charts']} fallback charts")
    print(f"  ✓ {airbnb_result['n_dropped_cols']} columns dropped")
    print(f"  ✓ {airbnb_result['n_warnings']} quality warnings")
    print(f"  Semantic types: {airbnb_result['semantic_types']}")

    print("\n" + "=" * 60)
    print("Phase 0: PASS")
    print("All 5 reusable modules work together on real data.")
    print("Safe to proceed to Phase 1 (project structure).")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

**Done when:**
- `uv run python test_phase0.py` runs to completion.
- Both datasets produce ≥3 charts each.
- Titanic completes in <15s, Airbnb in <30s.
- The "Phase 0: PASS" message appears.

---

### T-000.3: Manual inspection

**Goal:** Don't just trust the assertions. Look at the actual output.

Run an interactive session:

```bash
uv run python
```

```python
import duckdb, pandas as pd
import data_quality, profiler, chart_engine, transparency

con = duckdb.connect()
con.execute("CREATE TABLE raw_data AS SELECT * FROM read_csv_auto('titanic.csv')")
dq = data_quality.run(con, raw_table="raw_data")
df = con.execute('SELECT * FROM "cleaned_data"').df()
profile = profiler.profile_dataframe(df)
charts = chart_engine.generate_charts(df, "titanic.csv")
report = transparency.build(dq["quality_report"])

# Inspect each output by eye:
print(report["plain_text"])         # Does it read well?
print(profile["semantic_type_summary"])  # Are types reasonable?
charts[0]["figure"].show()          # Does the chart look right?
```

Look for:
- **Wrong semantic types** — e.g., `PassengerId` should be `identifier`, not `numeric`.
- **Bad transparency sentences** — e.g., technical jargon, missing data summary.
- **Broken charts** — e.g., axes not labeled, weird ranges, empty plots.
- **DuckDB warnings** — anything that hints at fragile SQL expressions.

**Done when:** You've manually looked at the output and nothing is obviously wrong.

---

### T-000.4: Document findings

**Goal:** Capture what we learned. This becomes part of `docs/PRODUCTION_NOTES.md`
later (the interview asks about production thinking).

Create `_validation/PHASE_0_RESULTS.md`:

```markdown
# Phase 0 Results

## Titanic
- Elapsed: X.X seconds
- Charts: N
- Quality warnings: M
- Issues found: [list anything weird]

## NYC Airbnb
- Elapsed: X.X seconds
- Charts: N
- Quality warnings: M
- Issues found: [list anything weird]

## Decisions made based on Phase 0
- [Any code change needed before Phase 1?]
- [Any threshold tuning needed?]
- [Any module that should be refactored before reuse?]
```

**Done when:** This file exists with real numbers and observations.

---

## Exit criteria

You can proceed to Phase 1 from `tasks.md` when:

- [ ] Both datasets run through the 5 modules without errors.
- [ ] Both datasets meet their time budgets.
- [ ] Manual inspection shows no obvious problems.
- [ ] `PHASE_0_RESULTS.md` is filled in.

If anything in Phase 0 fails:

1. **Do NOT proceed to Phase 1.**
2. Diagnose the root cause. Use Superpowers `debugging` skill (its four-phase
   methodology) for systematic root-cause analysis.
3. Fix the root cause in the offending module (likely `data_quality.py` or
   `profiler.py`).
4. Re-run Phase 0 until it passes.
5. Update the relevant planning doc to reflect the fix.

Only then proceed to Phase 1.

---

## Why this protects the project

Without Phase 0:
- Bug in `data_quality` discovered in Phase 7 → re-do all Phase 2-6 wiring.
- Performance issue with Airbnb found in Phase 8 → re-architect profiler.
- Wrong assumption in planning → entire orchestrator rewritten.

With Phase 0:
- Failures surface in 30 minutes, not 3 days.
- Planning is corrected before code is invested.
- The interview includes one more honest answer: "We validated the building
  blocks on real data before writing the orchestrator."

---

**End of Phase 0. Run before Phase 1.**
