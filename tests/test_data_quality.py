"""
Tests for quality/data_quality.py.

Regression coverage for the type-dispatch bug: columns that DuckDB
auto-detects as non-string scalar types (BOOLEAN, etc.) must not have
VARCHAR-only string operations (TRIM/LOWER/regexp_replace) applied to
them. Previously a BOOLEAN column fell through to the string pipeline
and crashed with: Binder Error: No function matches 'trim(BOOLEAN)'.
"""

from pathlib import Path

import duckdb
import pytest

from csv_dashboard.ingestion.loader import load_csv
from csv_dashboard.quality import data_quality


@pytest.fixture
def boolean_csv(tmp_path: Path) -> Path:
    p = tmp_path / "bools.csv"
    p.write_text(
        "name,active,age\n"
        "Alice,true,30\n"
        "Bob,false,25\n"
        "Carol,true,41\n"
        "Dave,false,33\n"
    )
    return p


def test_boolean_column_does_not_crash(boolean_csv: Path) -> None:
    con = load_csv(boolean_csv)
    try:
        # Sanity: DuckDB really did sniff 'active' as BOOLEAN.
        types = {r[0]: r[1] for r in con.execute("DESCRIBE raw_data").fetchall()}
        assert types["active"] == "BOOLEAN", types

        result = data_quality.run(con)  # must not raise BinderException
        assert "active" in result["clean_columns"]

        # The boolean column survives in the cleaned view with its values intact.
        rows = con.execute(
            'SELECT "active" FROM cleaned_data ORDER BY "name"'
        ).fetchall()
        assert [r[0] for r in rows] == [True, False, True, False]
    finally:
        con.close()


def test_nested_type_column_does_not_crash() -> None:
    """A VARCHAR[] (list) column reports typeof 'varchar[]' — it contains
    'varchar' but is not a plain string, so it must pass through, not enter
    the TRIM/LOWER pipeline."""
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE raw_data AS SELECT * FROM (VALUES "
        "(1, ['a', 'b']), (2, ['c']), (3, ['d', 'e'])"
        ") AS t(id, tags)"
    )
    try:
        assert dict(
            (r[0], r[1]) for r in con.execute("DESCRIBE raw_data").fetchall()
        )["tags"] == "VARCHAR[]"
        result = data_quality.run(con)  # must not raise
        assert "tags" in result["clean_columns"]
    finally:
        con.close()


def test_string_column_still_cleaned(boolean_csv: Path) -> None:
    """Guard against over-correcting: VARCHAR columns must still be trimmed."""
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE raw_data AS SELECT * FROM (VALUES "
        "('  Alice  ', 1), ('Bob', 2), ('  Carol', 3), ('Dave  ', 4)"
        ") AS t(name, id)"
    )
    try:
        data_quality.run(con)
        names = [r[0] for r in con.execute('SELECT "name" FROM cleaned_data').fetchall()]
        assert all(n == n.strip() for n in names), names
    finally:
        con.close()
