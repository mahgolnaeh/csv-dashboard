"""
data_quality.py
---------------
DuckDB-first data quality module.

Correct flow:
  1. DuckDB loads the raw CSV  (done by pipeline.py)
  2. This module receives the DuckDB connection + raw table name
  3. It runs detection queries directly on the raw table via SQL
  4. It builds a cleaned VIEW inside DuckDB:
       CREATE OR REPLACE VIEW cleaned_data AS SELECT ...
  5. The rest of the pipeline queries 'cleaned_data' — never 'raw_data'

What is fixed in the VIEW (SQL expressions):
  - Sentinel null strings  → NULL         (CASE WHEN col IN (...) THEN NULL)
  - Currency symbols       → DOUBLE       (TRY_CAST after regexp_replace)
  - Numeric strings        → DOUBLE       (TRY_CAST)
  - Whitespace             → trimmed      (TRIM())
  - Datetime strings       → TIMESTAMP    (TRY_CAST)
  - Dropped columns        → excluded from SELECT

What is warned only (reported, not changed):
  - Outliers
  - Mixed types
  - Inconsistent date formats
  - Duplicate rows
  - High missingness (>40%)

What is dropped (excluded from VIEW SELECT):
  - All-null columns
  - Constant columns (single unique value)
  - Duplicate columns (pandas .1 .2 suffixes)
"""

from __future__ import annotations

import re
import warnings
from typing import Any

import duckdb
import pandas as pd

# ── Config ─────────────────────────────────────────────────────────────────────

SENTINEL_NULLS = (
    "n/a", "na", "none", "null", "nil", "nan",
    "unknown", "undefined", "-", "--", "?", "missing",
    "not available", "not applicable", "n.a.",
)

OUTLIER_IQR_MULTIPLIER = 3.0
HIGH_NULL_THRESHOLD    = 0.40
NUMERIC_CAST_THRESHOLD = 0.95
MIXED_TYPE_THRESHOLD   = 0.50
DATE_PARSE_THRESHOLD   = 0.95
DATE_MIXED_THRESHOLD   = 0.50


# ── Main entry point ───────────────────────────────────────────────────────────

def run(
    con: duckdb.DuckDBPyConnection,
    raw_table: str = "raw_data",
) -> dict[str, Any]:
    """
    Analyze raw_table, create a cleaned VIEW, return a report.

    Args:
        con:        open DuckDB connection with raw_table already registered
        raw_table:  name of the raw table (default: "raw_data")

    Returns:
        {
            "view_name":      str,         # "cleaned_data" — query this from now on
            "quality_report": list[dict],
            "dropped_cols":   list[str],
            "has_issues":     bool,
            "llm_context":    str,
            "clean_columns":  list[str],
        }
    """
    report: list[dict] = []
    dropped: list[str] = []

    raw_cols  = _get_columns(con, raw_table)
    row_count = con.execute(f'SELECT COUNT(*) FROM "{raw_table}"').fetchone()[0]

    # ── 1. Structural checks: decide which columns to keep ────────────────────
    keep_cols: list[str] = []

    seen_bases: set[str] = set()
    for col in raw_cols:
        base = re.sub(r"\.\d+$", "", col)
        if base in seen_bases:
            dropped.append(col)
            _add(report, "info", issue="duplicate column removed",
                 detail=f"'{col}' is a duplicate of '{base}'. Excluded from view.")
            continue
        seen_bases.add(base)
        keep_cols.append(col)

    for col in keep_cols[:]:
        q = _q(col)

        null_count = con.execute(
            f'SELECT COUNT(*) FROM "{raw_table}" WHERE {q} IS NULL'
        ).fetchone()[0]
        if null_count == row_count:
            keep_cols.remove(col)
            dropped.append(col)
            _add(report, "drop", col=col, issue="all-null column removed",
                 detail="100% of values are NULL. No insight possible.")
            continue

        unique_count = con.execute(
            f'SELECT COUNT(DISTINCT {q}) FROM "{raw_table}"'
        ).fetchone()[0]
        if unique_count <= 1:
            keep_cols.remove(col)
            dropped.append(col)
            _add(report, "drop", col=col, issue="constant column removed",
                 detail="Single unique value across all rows. No insight possible.")
            continue

    # ── 2. Per-column analysis → build SELECT expressions for the VIEW ────────
    select_exprs: list[str] = []
    for col in keep_cols:
        expr, col_reports = _analyze_column(con, raw_table, col, row_count)
        select_exprs.append(f"  {expr} AS {_q(col)}")
        report.extend(col_reports)

    # ── 3. Duplicate row detection (warn only) ────────────────────────────────
    col_list = ", ".join(_q(c) for c in keep_cols)
    try:
        dup_count = con.execute(
            f'SELECT COUNT(*) FROM ('
            f'  SELECT {col_list}, COUNT(*) AS n FROM "{raw_table}"'
            f'  GROUP BY {col_list} HAVING n > 1'
            f') t'
        ).fetchone()[0]
        if dup_count > 0:
            _add(report, "warn", issue="duplicate rows detected",
                 detail=f"{dup_count} row group(s) appear more than once. "
                        "Rows kept — removing may affect aggregate counts.")
    except Exception:
        pass

    # ── 4. Create the cleaned VIEW ────────────────────────────────────────────
    view_name = "cleaned_data"
    select_sql = ",\n".join(select_exprs)
    view_sql = f'CREATE OR REPLACE VIEW "{view_name}" AS\nSELECT\n{select_sql}\nFROM "{raw_table}"'
    con.execute(view_sql)

    return {
        "view_name":      view_name,
        "quality_report": report,
        "dropped_cols":   dropped,
        "has_issues":     any(r["severity"] in ("warn", "drop") for r in report),
        "llm_context":    _build_llm_context(report),
        "clean_columns":  list(keep_cols),
    }


# ── Per-column analysis ────────────────────────────────────────────────────────

def _analyze_column(
    con: duckdb.DuckDBPyConnection,
    table: str,
    col: str,
    row_count: int,
) -> tuple[str, list[dict]]:
    """
    Returns (sql_expression_for_view, report_entries).
    The expression transforms the raw column into its clean form.
    """
    report: list[dict] = []
    q = _q(col)

    # Detect native DuckDB type
    dtype_row = con.execute(
        f'SELECT typeof({q}) FROM "{table}" WHERE {q} IS NOT NULL LIMIT 1'
    ).fetchone()
    dtype = dtype_row[0].lower() if dtype_row else "varchar"
    is_numeric = any(t in dtype for t in
                     ("int", "float", "double", "decimal", "bigint", "hugeint", "real"))
    is_date    = any(t in dtype for t in ("date", "timestamp"))
    # Exact match, not substring: nested types like "varchar[]", "struct(...)"
    # or "map(varchar, varchar)" contain "varchar"/"char" but are NOT plain
    # strings, and TRIM/LOWER would fail on them just like on BOOLEAN.
    is_string  = dtype in ("varchar", "text", "string", "char", "bpchar")

    # Already a proper numeric or date column — just check for outliers
    if is_numeric:
        _warn_outliers(con, table, col, report)
        return q, report

    if is_date:
        return q, report

    # Any other scalar type (BOOLEAN, BLOB, UUID, ...) is already typed and
    # carries no string artifacts. The string pipeline below uses VARCHAR-only
    # functions (TRIM/LOWER/regexp_replace), so applying it to e.g. BOOLEAN
    # raises a Binder Error. Pass these columns through unchanged.
    if not is_string:
        return q, report

    # ── String column pipeline ────────────────────────────────────────────────
    sample = _sample_strings(con, table, col)
    if not sample:
        return q, report

    expr = q  # will be wrapped step by step

    # Step A: sentinel nulls → NULL
    sentinel_list = ", ".join(f"'{s}'" for s in SENTINEL_NULLS)
    sentinel_count = con.execute(
        f'SELECT COUNT(*) FROM "{table}" '
        f'WHERE LOWER(TRIM({q})) IN ({sentinel_list})'
    ).fetchone()[0]

    if sentinel_count > 0:
        expr = (
            f"CASE WHEN LOWER(TRIM({q})) IN ({sentinel_list}) "
            f"THEN NULL ELSE {q} END"
        )
        _add(report, "info", col=col,
             issue="sentinel null strings → NULL in view",
             detail=f"{sentinel_count} values like 'N/A', 'unknown', '-' replaced.")

    # Step B: currency symbols → DOUBLE
    currency_hits = sum(
        1 for v in sample
        if re.match(r"^[€$£¥₹]?\s*[\d,]+\.?\d*\s*[€$£¥₹]?$", v.strip())
    )
    if len(sample) > 0 and currency_hits / len(sample) >= 0.7:
        stripped = f"regexp_replace({expr}, '[€$£¥₹,\\s]', '', 'g')"
        cast     = f"TRY_CAST({stripped} AS DOUBLE)"
        non_null = con.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE {q} IS NOT NULL'
        ).fetchone()[0]
        success = con.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE '
            f'TRY_CAST(regexp_replace({q}, \'[€$£¥₹,\\s]\', \'\', \'g\') AS DOUBLE) IS NOT NULL '
            f'AND {q} IS NOT NULL'
        ).fetchone()[0]
        if non_null > 0 and success / non_null >= NUMERIC_CAST_THRESHOLD:
            expr = cast
            _add(report, "info", col=col,
                 issue="currency symbols stripped, cast to DOUBLE in view",
                 detail=f"Example original value: '{sample[0]}'")
        return expr, report

    # Step C: numeric strings → DOUBLE
    numeric_hits = sum(1 for v in sample if _is_numeric_str(v))
    numeric_rate = numeric_hits / len(sample) if sample else 0

    if numeric_rate >= NUMERIC_CAST_THRESHOLD:
        expr = f"TRY_CAST({expr} AS DOUBLE)"
        _add(report, "info", col=col,
             issue="numeric strings cast to DOUBLE in view",
             detail=f"{numeric_rate:.0%} of sampled values are valid numbers.")
        _warn_outliers(con, table, col, report)
        return expr, report

    if MIXED_TYPE_THRESHOLD <= numeric_rate < NUMERIC_CAST_THRESHOLD:
        _add(report, "warn", col=col,
             issue="mixed types detected (numeric + text)",
             detail=(
                 f"{numeric_rate:.0%} of values look numeric, "
                 f"{1-numeric_rate:.0%} are text. "
                 "Column kept as text. Avoid using as a numeric axis."
             ))
        return f"TRIM({expr})", report

    # Step D: whitespace trimming (always safe)
    expr = f"TRIM({expr})"

    # Step E: datetime strings → TIMESTAMP
    parsed = 0
    for v in sample[:50]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pd.to_datetime(v, errors="raise")
            parsed += 1
        except Exception:
            pass
    date_rate = parsed / min(len(sample), 50) if sample else 0

    if date_rate >= DATE_PARSE_THRESHOLD:
        expr = f"TRY_CAST({expr} AS TIMESTAMP)"
        _add(report, "info", col=col,
             issue="datetime strings cast to TIMESTAMP in view",
             detail="Column consistently contains dates and was converted.")
    elif date_rate >= DATE_MIXED_THRESHOLD:
        _add(report, "warn", col=col,
             issue="inconsistent date formats detected",
             detail=(
                 f"{date_rate:.0%} of sampled values parsed as dates. "
                 "Multiple formats likely. Column kept as text. "
                 "Time-series charts may not work correctly."
             ))

    # Step F: high missingness warning
    null_count = con.execute(
        f'SELECT COUNT(*) FROM "{table}" WHERE {q} IS NULL'
    ).fetchone()[0]
    if row_count > 0 and null_count / row_count > HIGH_NULL_THRESHOLD:
        _add(report, "warn", col=col,
             issue="high missing values",
             detail=f"{null_count/row_count:.0%} of values are missing. "
                    "Charts using this column may be misleading.")

    return expr, report


# ── Outlier warning via DuckDB percentile queries ──────────────────────────────

def _warn_outliers(
    con: duckdb.DuckDBPyConnection,
    table: str,
    col: str,
    report: list[dict],
) -> None:
    q = _q(col)
    try:
        row = con.execute(
            f'SELECT '
            f'  PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {q}) AS q1,'
            f'  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {q}) AS q3,'
            f'  MIN({q}), MAX({q}) '
            f'FROM "{table}" WHERE {q} IS NOT NULL'
        ).fetchone()
        if not row or row[0] is None:
            return
        q1, q3, mn, mx = row
        iqr = q3 - q1
        if iqr == 0:
            return
        lower = q1 - OUTLIER_IQR_MULTIPLIER * iqr
        upper = q3 + OUTLIER_IQR_MULTIPLIER * iqr
        n_out = con.execute(
            f'SELECT COUNT(*) FROM "{table}" '
            f'WHERE {q} IS NOT NULL AND ({q} < {lower} OR {q} > {upper})'
        ).fetchone()[0]
        if n_out > 0:
            _add(report, "warn", col=col,
                 issue="extreme outliers detected",
                 detail=(
                     f"{n_out} value(s) outside IQR×{OUTLIER_IQR_MULTIPLIER} "
                     f"(expected [{lower:.2f}, {upper:.2f}], "
                     f"actual [{mn:.2f}, {mx:.2f}]). "
                     "Outliers kept. Charts will mark them."
                 ))
    except Exception:
        pass


# ── LLM context builder ────────────────────────────────────────────────────────

def _build_llm_context(report: list[dict]) -> str:
    issues = [r for r in report if r["severity"] in ("warn", "drop")]
    if not issues:
        return "Data quality: no issues found. All columns are clean."
    lines = ["Data quality context (use when deciding which charts to generate):"]
    for r in issues:
        col   = r.get("column", "")
        label = "DROPPED" if r["severity"] == "drop" else "WARNING"
        prefix = f"{col}: " if col else ""
        lines.append(f"- {label} {prefix}{r['issue']}. {r['detail']}")
    return "\n".join(lines)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    return [r[0] for r in con.execute(f'DESCRIBE "{table}"').fetchall()]


def _q(col: str) -> str:
    return f'"{col}"'


def _sample_strings(
    con: duckdb.DuckDBPyConnection, table: str, col: str, n: int = 200
) -> list[str]:
    q = _q(col)
    rows = con.execute(
        f'SELECT {q}::VARCHAR FROM "{table}" WHERE {q} IS NOT NULL LIMIT {n}'
    ).fetchall()
    return [r[0] for r in rows if r[0] is not None]


def _is_numeric_str(v: str) -> bool:
    try:
        float(v.replace(",", ""))
        return True
    except ValueError:
        return False


def _add(report: list[dict], severity: str, *,
         col: str = "", issue: str, detail: str) -> None:
    entry: dict[str, str] = {"severity": severity, "issue": issue, "detail": detail}
    if col:
        entry["column"] = col
    report.append(entry)
