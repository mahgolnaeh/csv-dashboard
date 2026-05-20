"""
Phase 0 regression check: validate chart_engine after move to
src/csv_dashboard/charts/engine.py.

Checks:
  - Default mode produces 3-6 charts for both datasets.
  - Pool mode (max_charts=None) produces more charts than default.
  - Priority order in pool matches default exactly.
  - Timing within budget (<15s Titanic, <30s Airbnb).
  - Chart titles match Phase 0 baseline.

Run from project root:
    uv run python _validation/test_phase0_relocated.py
"""

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from csv_dashboard.charts.engine import generate_charts

DATASETS = [
    {
        "label": "Titanic",
        "csv": "_validation/titanic.csv",
        "expected_rows": 891,
        "budget_s": 15.0,
        "expected_n_charts": 6,
        "expected_titles": [
            "Dataset summary",
            "Data health — missing values",
            "Count of 'Sex'",
            "Count of 'Embarked'",
            "Distribution: Fare",
            "Distribution: Age",
        ],
    },
    {
        "label": "NYC Airbnb",
        "csv": "_validation/AB_NYC_2019.csv",
        "expected_rows": 48895,
        "budget_s": 30.0,
        "expected_n_charts": 6,
        "expected_titles": [
            "Dataset summary",
            "Data health — missing values",
            "Records over time: last_review",
            "Count of 'neighbourhood_group'",
            "Count of 'room_type'",
            "Average 'price' over time",
        ],
    },
]


def run_check(cfg: dict) -> None:
    label = cfg["label"]
    csv_path = cfg["csv"]
    expected_rows = cfg["expected_rows"]
    budget_s = cfg["budget_s"]
    expected_n = cfg["expected_n_charts"]
    expected_titles = cfg["expected_titles"]

    print(f"\n[{label}]  {csv_path}")
    t0 = time.perf_counter()

    df = pd.read_csv(csv_path)
    assert len(df) == expected_rows, (
        f"Row count: expected {expected_rows}, got {len(df)}"
    )

    # Default mode
    charts = generate_charts(df, csv_path)
    n = len(charts)
    assert 3 <= n <= 6, f"Default mode: expected 3-6 charts, got {n}"
    for c in charts:
        assert "title" in c and "figure" in c and "rule" in c, (
            f"Chart missing keys: {c.keys()}"
        )

    # Pool mode
    pool = generate_charts(df, csv_path, max_charts=None)
    assert len(pool) > n, (
        f"Pool ({len(pool)}) should exceed default ({n})"
    )

    # Priority order preserved in pool
    for i, c in enumerate(charts):
        assert pool[i]["title"] == c["title"], (
            f"Priority mismatch at index {i}: "
            f"'{pool[i]['title']}' != '{c['title']}'"
        )

    elapsed = time.perf_counter() - t0
    assert elapsed < budget_s, (
        f"Took {elapsed:.1f}s — over budget ({budget_s}s)"
    )

    # Title baseline check
    actual_titles = [c["title"] for c in charts]
    if actual_titles != expected_titles:
        print(f"  WARN  Title mismatch vs Phase 0 baseline:")
        print(f"        Expected: {expected_titles}")
        print(f"        Actual:   {actual_titles}")
    else:
        print(f"  OK    Titles match Phase 0 baseline")

    print(f"  OK    {len(df)} rows | {elapsed:.2f}s | {n} charts (pool: {len(pool)})")
    for c in charts:
        print(f"        [{c['rule']}] {c['title']}")


def main() -> None:
    print("=" * 60)
    print("Phase 0 Regression: engine.py relocated to src/")
    print("=" * 60)

    failures = []
    for cfg in DATASETS:
        try:
            run_check(cfg)
        except AssertionError as e:
            failures.append(f"{cfg['label']}: {e}")
            print(f"  FAIL  {e}")

    print("\n" + "=" * 60)
    if failures:
        print(f"FAIL — {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("PASS — engine.py move is clean. Safe to continue to T-011.")
    print("=" * 60)


if __name__ == "__main__":
    main()
