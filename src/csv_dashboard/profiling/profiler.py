"""
profiler.py — Hybrid Data Profiling Module
Telekom AI & Digital Innovation MVP

Strategy:
  - DuckDB  → heavy stats (min, max, mean, std, quantiles, null%, skewness, IQR outliers)
  - Custom  → things DuckDB can't do (semantic types, sample values, warnings)

Input:  pd.DataFrame (any domain, any size)
Output: structured dict, fully JSON-serializable (~1000 tokens for Haiku)
"""

from typing import Any

import duckdb
import numpy as np
import pandas as pd

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

HIGH_CARDINALITY_RATIO = 0.5       # unique/total > this → warn
NEAR_CONSTANT_UNIQUE_THRESHOLD = 2 # unique count <= this → warn
SAMPLE_VALUE_COUNT = 5             # how many sample values to show per column
HIGH_MISSING_THRESHOLD = 50.0      # null% > this → warn

DATETIME_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
    "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%Y%m%d",
]


# ─── DUCKDB STATS ─────────────────────────────────────────────────────────────

def _duckdb_stats(df: pd.DataFrame) -> tuple[dict, dict]:
    """
    Use DuckDB to compute all heavy statistics in one pass.
    Returns:
      base  — per-column from SUMMARIZE (min, max, avg, std, quantiles, nulls)
      extra — per-column skewness and IQR outlier count (numeric only)
    """
    con = duckdb.connect()
    con.register("_df", df)

    # SUMMARIZE gives base stats for all columns
    summarize = con.execute("SUMMARIZE _df").fetchdf()

    base = {}
    for _, row in summarize.iterrows():
        col = row["column_name"]
        base[col] = {
            "duckdb_type":  row["column_type"],
            "count":        int(row["count"]),
            "null_pct":     float(row["null_percentage"]),
            "approx_unique": int(row["approx_unique"]),
            "min":  row["min"],
            "max":  row["max"],
            "avg":  row["avg"],
            "std":  row["std"],
            "q25":  row["q25"],
            "q50":  row["q50"],
            "q75":  row["q75"],
        }

    # Skewness + IQR outliers — only for numeric columns
    numeric_types = {"BIGINT", "INTEGER", "DOUBLE", "FLOAT", "HUGEINT", "SMALLINT", "DECIMAL"}
    numeric_cols = [c for c, info in base.items() if info["duckdb_type"] in numeric_types]

    extra = {}
    for col in numeric_cols:
        safe = f'"{col}"'
        try:
            skew = con.execute(f"SELECT skewness({safe}) FROM _df").fetchone()[0]
        except Exception:
            skew = None
        try:
            outliers = con.execute(f"""
                WITH s AS (
                    SELECT
                        quantile_cont({safe}, 0.25) AS q1,
                        quantile_cont({safe}, 0.75) AS q3
                    FROM _df
                )
                SELECT COUNT(*) FROM _df, s
                WHERE {safe} < s.q1 - 1.5*(s.q3 - s.q1)
                   OR {safe} > s.q3 + 1.5*(s.q3 - s.q1)
            """).fetchone()[0]
        except Exception:
            outliers = None

        extra[col] = {
            "skewness":          round(float(skew), 4) if skew is not None else None,
            "outlier_count_iqr": int(outliers) if outliers is not None else None,
        }

    con.close()
    return base, extra


# ─── SEMANTIC TYPE DETECTION ──────────────────────────────────────────────────

def _detect_semantic_type(col: pd.Series, duckdb_type: str, unique_count: int, row_count: int) -> str:
    """
    Detect semantic type using DuckDB type hint + column content.
    DuckDB tells us the storage type; we figure out the meaning.

    Returns one of: 'boolean', 'datetime', 'identifier', 'numeric', 'categorical', 'text'
    """
    non_null = col.dropna()
    if len(non_null) == 0:
        return "categorical"

    # 1. Boolean
    if col.dtype == bool or duckdb_type == "BOOLEAN":
        return "boolean"
    if col.dtype == object:
        lower_vals = set(str(v).strip().lower() for v in non_null.unique())
        if lower_vals <= {"true", "false", "yes", "no", "1", "0", "t", "f", "y", "n"}:
            return "boolean"

    # 2. Datetime — native or DuckDB-detected
    if pd.api.types.is_datetime64_any_dtype(col) or duckdb_type in ("DATE", "TIMESTAMP", "TIME"):
        return "datetime"

    # 3. Datetime — VARCHAR that parses as date
    if col.dtype == object:
        sample = non_null.head(50)
        for fmt in DATETIME_FORMATS:
            try:
                parsed = pd.to_datetime(sample, format=fmt, errors="raise")
                if parsed.notna().sum() >= len(sample) * 0.8:
                    return "datetime"
            except Exception:
                continue

    # 4. Integer — could be real number or an identifier
    if duckdb_type in ("BIGINT", "INTEGER", "HUGEINT", "SMALLINT"):
        unique_ratio = unique_count / max(row_count, 1)
        if unique_ratio > 0.9 and unique_count > 100:
            return "identifier"
        return "numeric"

    # 5. Float
    if duckdb_type in ("DOUBLE", "FLOAT", "DECIMAL"):
        return "numeric"

    # 6. VARCHAR — identifier / text / categorical
    if col.dtype == object:
        unique_ratio = unique_count / max(row_count, 1)
        avg_len = non_null.astype(str).str.len().mean()
        if unique_ratio > 0.9 and unique_count > 50:
            return "identifier"
        if avg_len > 50:
            return "text"
        return "categorical"

    return "categorical"


# ─── SAMPLE VALUES ────────────────────────────────────────────────────────────

def _sample_values(col: pd.Series, n: int = SAMPLE_VALUE_COUNT) -> list:
    """Return n representative non-null values, JSON-safe types."""
    non_null = col.dropna()
    if len(non_null) == 0:
        return []
    unique_vals = non_null.unique()
    candidates = unique_vals if len(unique_vals) <= n else pd.Series(unique_vals).sample(n, random_state=42).values
    result = []
    for v in candidates:
        if isinstance(v, np.integer):
            result.append(int(v))
        elif isinstance(v, np.floating):
            result.append(round(float(v), 4))
        elif isinstance(v, np.bool_):
            result.append(bool(v))
        elif pd.isna(v):
            continue
        else:
            result.append(str(v))
    return result


def _to_float(val) -> float | None:
    """Safely cast DuckDB string/None stat to float."""
    try:
        return round(float(val), 4) if val is not None else None
    except (ValueError, TypeError):
        return None


# ─── MAIN FUNCTION ────────────────────────────────────────────────────────────

def profile_dataframe(df: pd.DataFrame) -> dict:
    """
    Hybrid profiling: DuckDB for stats, custom logic for semantic types.

    Args:
        df: Input DataFrame (any domain, any size)

    Returns:
        JSON-serializable dict, ready for Claude Haiku insight layer
    """
    row_count = int(df.shape[0])
    col_count = int(df.shape[1])

    # Duplicate rows via DuckDB
    con = duckdb.connect()
    con.register("_df", df)
    distinct = con.execute("SELECT COUNT(*) FROM (SELECT DISTINCT * FROM _df)").fetchone()[0]
    con.close()
    duplicate_row_count = row_count - int(distinct)

    # DuckDB stats (one pass for everything)
    duckdb_base, duckdb_extra = _duckdb_stats(df)

    columns_profile: dict[str, Any] = {}
    warnings: list[dict] = []
    semantic_summary: dict[str, list] = {
        "numeric": [], "categorical": [], "datetime": [],
        "boolean": [], "text": [], "identifier": [],
    }

    for col_name in df.columns:
        col = df[col_name]
        key = str(col_name)
        stats = duckdb_base.get(key, {})

        null_pct     = float(stats.get("null_pct", 0.0))
        missing_count = int(round(null_pct * row_count / 100))
        unique_count  = int(stats.get("approx_unique", col.nunique()))
        duckdb_type   = stats.get("duckdb_type", "VARCHAR")

        semantic_type = _detect_semantic_type(col, duckdb_type, unique_count, row_count)

        col_profile: dict[str, Any] = {
            "dtype":         str(col.dtype),
            "duckdb_type":   duckdb_type,
            "semantic_type": semantic_type,
            "missing_count": missing_count,
            "missing_pct":   round(null_pct, 2),
            "unique_count":  unique_count,
            "sample_values": _sample_values(col),
        }

        # Numeric summary — DuckDB stats + skewness/outliers
        if semantic_type == "numeric":
            extra = duckdb_extra.get(key, {})
            col_profile["numeric_summary"] = {
                "min":               _to_float(stats.get("min")),
                "max":               _to_float(stats.get("max")),
                "mean":              _to_float(stats.get("avg")),
                "median":            _to_float(stats.get("q50")),
                "std":               _to_float(stats.get("std")),
                "q1":                _to_float(stats.get("q25")),
                "q3":                _to_float(stats.get("q75")),
                "skewness":          extra.get("skewness"),
                "outlier_count_iqr": extra.get("outlier_count_iqr"),
            }

        # ── Warnings ──────────────────────────────────────────────────────────
        if semantic_type == "categorical":
            ratio = unique_count / max(row_count, 1)
            if ratio > HIGH_CARDINALITY_RATIO and unique_count > 10:
                col_profile["warning"] = "high_cardinality"
                warnings.append({
                    "column": key, "type": "high_cardinality",
                    "detail": f"{unique_count} unique / {row_count} rows ({round(ratio*100,1)}%)"
                })

        if unique_count <= NEAR_CONSTANT_UNIQUE_THRESHOLD and missing_count < row_count:
            label = "constant" if unique_count <= 1 else "near_constant"
            col_profile["warning"] = label
            warnings.append({"column": key, "type": label, "detail": f"Only {unique_count} unique value(s)"})

        if null_pct > HIGH_MISSING_THRESHOLD:
            warnings.append({"column": key, "type": "high_missing", "detail": f"{round(null_pct,1)}% missing"})

        columns_profile[key] = col_profile
        if semantic_type in semantic_summary:
            semantic_summary[semantic_type].append(key)

    return {
        "row_count":            row_count,
        "column_count":         col_count,
        "column_names":         [str(c) for c in df.columns.tolist()],
        "duplicate_row_count":  duplicate_row_count,
        "semantic_type_summary": semantic_summary,
        "columns":              columns_profile,
        "warnings":             warnings,
    }
