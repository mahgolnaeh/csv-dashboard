"""
T-000.3: Manual inspection script for Phase 0.
Run after test_phase0.py passes to verify output quality by eye.
"""

import duckdb
import data_quality
import profiler
import transparency
import chart_engine


def inspect(csv_path: str, expected_rows: int, label: str):
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")

    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE raw_data AS SELECT * FROM read_csv_auto('{csv_path}')"
    )
    dq = data_quality.run(con, raw_table="raw_data")
    df = con.execute('SELECT * FROM "cleaned_data"').df()
    profile = profiler.profile_dataframe(df)
    charts = chart_engine.generate_charts(df, csv_path)
    report = transparency.build(dq["quality_report"])
    con.close()

    print("\n--- Transparency text ---")
    print(report["plain_text"])

    print("\n--- Semantic types ---")
    for stype, cols in profile["semantic_type_summary"].items():
        if cols:
            print(f"  {stype}: {cols}")

    print("\n--- Quality report entries ---")
    for r in dq["quality_report"]:
        col = r.get("column", "")
        print(f"  [{r['severity']}] {(col + ': ') if col else ''}{r['issue']}")

    print("\n--- Column types in cleaned_data ---")
    for col, info in profile["columns"].items():
        missing = f"  ({info['missing_pct']}% missing)" if info["missing_pct"] > 0 else ""
        print(f"  {col}: {info['duckdb_type']} -> {info['semantic_type']}{missing}")

    print("\n--- Charts generated ---")
    for c in charts:
        print(f"  [{c['rule']}] {c['title']}")


if __name__ == "__main__":
    inspect("titanic.csv", 891, "TITANIC (891 rows)")
    inspect("AB_NYC_2019.csv", 48895, "NYC AIRBNB (48895 rows)")
