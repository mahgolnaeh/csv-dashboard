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

    # Step 2: data_quality — creates cleaned_data VIEW
    dq = data_quality.run(con, raw_table="raw_data")
    assert dq["view_name"] == "cleaned_data"
    assert isinstance(dq["quality_report"], list)
    assert isinstance(dq["dropped_cols"], list)
    assert isinstance(dq["llm_context"], str)

    # Sanity: VIEW exists and is queryable
    view_row_count = con.execute('SELECT COUNT(*) FROM "cleaned_data"').fetchone()[0]
    # data_quality only drops columns, not rows — row count must match
    assert view_row_count == expected_rows, (
        f"cleaned_data row count {view_row_count} != expected {expected_rows}"
    )

    # Step 3: profiler
    df = con.execute('SELECT * FROM "cleaned_data"').df()
    profile = profiler.profile_dataframe(df)
    assert profile["row_count"] == expected_rows
    assert profile["column_count"] >= 1
    assert "semantic_type_summary" in profile
    assert "columns" in profile

    # Step 4: chart_engine (deterministic fallback — no LLM)
    # Default mode: max_charts=6 (non-technical user view)
    charts = chart_engine.generate_charts(df, csv_path)
    assert 3 <= len(charts) <= 6, f"Expected 3-6 charts in default mode, got {len(charts)}"
    for c in charts:
        assert "title" in c
        assert "figure" in c
        assert "rule" in c

    # Pool mode: max_charts=None (all candidates)
    charts_pool = chart_engine.generate_charts(df, csv_path, max_charts=None)
    assert len(charts_pool) > len(charts), (
        f"Pool mode should have more charts than default ({len(charts_pool)} vs {len(charts)})"
    )
    # The first N charts in pool mode must match default mode exactly (same priority order)
    for i, c in enumerate(charts):
        assert charts_pool[i]["title"] == c["title"], (
            f"Priority order mismatch at index {i}: '{charts_pool[i]['title']}' != '{c['title']}'"
        )

    # Step 5: transparency
    report = transparency.build(dq["quality_report"])
    assert "plain_text" in report
    assert "sentences" in report
    assert isinstance(report["sentences"], list)

    elapsed = time.perf_counter() - t0
    assert elapsed < time_budget_s, (
        f"Pipeline took {elapsed:.1f}s, budget was {time_budget_s}s"
    )

    con.close()

    n_warnings = len([r for r in dq["quality_report"] if r["severity"] == "warn"])

    return {
        "csv": csv_path,
        "rows": raw_row_count,
        "elapsed_s": round(elapsed, 2),
        "n_charts": len(charts),
        "n_charts_pool": len(charts_pool),
        "chart_titles": [c["title"] for c in charts],
        "chart_rules": [c["rule"] for c in charts],
        "n_dropped_cols": len(dq["dropped_cols"]),
        "dropped_cols": dq["dropped_cols"],
        "n_warnings": n_warnings,
        "semantic_types": profile["semantic_type_summary"],
        "transparency_lines": len(report["sentences"]),
        "transparency_text": report["plain_text"],
    }


def main():
    print("=" * 60)
    print("Phase 0 Validation")
    print("=" * 60)

    # Titanic — small dataset, 15s budget
    print("\n[1/2] Testing Titanic (891 rows, 15s budget)...")
    titanic_result = run_pipeline("titanic.csv", 891, 15.0)
    print(f"  OK  {titanic_result['rows']} rows in {titanic_result['elapsed_s']}s")
    print(f"  OK  {titanic_result['n_charts']} fallback charts (pool: {titanic_result['n_charts_pool']})")
    for t in titanic_result['chart_titles']:
        print(f"       - {t}")
    print(f"  OK  {titanic_result['n_dropped_cols']} columns dropped: {titanic_result['dropped_cols']}")
    print(f"  OK  {titanic_result['n_warnings']} quality warnings")
    print(f"  OK  {titanic_result['transparency_lines']} transparency sentences")
    print(f"  Semantic types: {titanic_result['semantic_types']}")

    # NYC Airbnb — large dataset, 30s budget
    print("\n[2/2] Testing NYC Airbnb (48895 rows, 30s budget)...")
    airbnb_result = run_pipeline("AB_NYC_2019.csv", 48895, 30.0)
    print(f"  OK  {airbnb_result['rows']} rows in {airbnb_result['elapsed_s']}s")
    print(f"  OK  {airbnb_result['n_charts']} fallback charts (pool: {airbnb_result['n_charts_pool']})")
    for t in airbnb_result['chart_titles']:
        print(f"       - {t}")
    print(f"  OK  {airbnb_result['n_dropped_cols']} columns dropped: {airbnb_result['dropped_cols']}")
    print(f"  OK  {airbnb_result['n_warnings']} quality warnings")
    print(f"  OK  {airbnb_result['transparency_lines']} transparency sentences")
    print(f"  Semantic types: {airbnb_result['semantic_types']}")

    print("\n" + "=" * 60)
    print("Phase 0: PASS")
    print("All 5 reusable modules work together on real data.")
    print("Safe to proceed to Phase 1 (project structure).")
    print("=" * 60)

    return titanic_result, airbnb_result


if __name__ == "__main__":
    main()
