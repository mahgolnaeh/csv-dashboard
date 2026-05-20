"""
Debug script: check dtypes of cleaned_data columns and chart_engine column classification.
"""

import pandas as pd
import duckdb
import data_quality
import chart_engine


def debug(csv_path: str, label: str):
    print(f"\n{'='*50}")
    print(f"{label}")
    print(f"{'='*50}")

    con = duckdb.connect()
    con.execute(
        f"CREATE TABLE raw_data AS SELECT * FROM read_csv_auto('{csv_path}')"
    )
    data_quality.run(con, raw_table="raw_data")
    df = con.execute('SELECT * FROM "cleaned_data"').df()
    con.close()

    print("\n--- DataFrame dtypes ---")
    for col in df.columns:
        s = df[col]
        is_num = pd.api.types.is_numeric_dtype(s)
        is_obj = s.dtype == object
        try:
            is_cat = pd.api.types.is_categorical_dtype(s)
        except Exception as e:
            is_cat = f"ERROR: {e}"
        print(f"  {col}: dtype={s.dtype}  is_numeric={is_num}  dtype==object={is_obj}  is_categorical={is_cat}")

    # Replicate chart_engine column classification
    dt_cols = chart_engine._infer_datetime(df)
    numeric_cols = []
    categorical_cols = []
    skipped_cols = []

    for col in df.columns:
        s = df[col]
        if chart_engine._is_identifier(col, s):
            skipped_cols.append((col, "identifier"))
            continue
        if col not in dt_cols and chart_engine._missing_fraction(s) > chart_engine.MISSING_THRESHOLD:
            skipped_cols.append((col, "high missing"))
            continue
        if col in dt_cols:
            continue
        if pd.api.types.is_numeric_dtype(s):
            numeric_cols.append(col)
        elif s.dtype == object or pd.api.types.is_categorical_dtype(s):
            categorical_cols.append(col)
        else:
            skipped_cols.append((col, f"unclassified dtype={s.dtype}"))

    print(f"\n--- chart_engine classification ---")
    print(f"  numeric:     {numeric_cols}")
    print(f"  categorical: {categorical_cols}")
    print(f"  datetime:    {dt_cols}")
    print(f"  skipped:     {skipped_cols}")


if __name__ == "__main__":
    debug("titanic.csv", "TITANIC")
    debug("AB_NYC_2019.csv", "NYC AIRBNB")
