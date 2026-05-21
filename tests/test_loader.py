"""
Tests for ingestion/loader.py — written BEFORE implementation (TDD).

Three cases per tasks.md T-021:
  1. Loading a valid CSV returns a DuckDB connection with raw_data registered.
  2. Loading a nonexistent file raises FileLoadError.
  3. Loading a malformed file raises FileLoadError.
"""

from pathlib import Path

import pytest

from csv_dashboard.ingestion.loader import FileLoadError, load_csv

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_csv(tmp_path: Path) -> Path:
    p = tmp_path / "sample.csv"
    p.write_text("name,age,score\nAlice,30,9.5\nBob,25,8.1\nCarol,35,7.9\n")
    return p


@pytest.fixture
def malformed_file(tmp_path: Path) -> Path:
    p = tmp_path / "bad.csv"
    p.write_bytes(b"\x00\x01\x02\xff\xfe garbage not a csv \x00")
    return p


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_valid_csv_returns_connection_with_raw_data(valid_csv: Path) -> None:
    con = load_csv(valid_csv)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        assert "raw_data" in tables, f"raw_data not found in tables: {tables}"
        count = con.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
        assert count == 3, f"Expected 3 rows, got {count}"
        cols = {row[0] for row in con.execute("DESCRIBE raw_data").fetchall()}
        assert {"name", "age", "score"} == cols, f"Unexpected columns: {cols}"
    finally:
        con.close()


def test_nonexistent_file_raises_file_load_error() -> None:
    with pytest.raises(FileLoadError):
        load_csv("/nonexistent/path/that/does/not/exist.csv")


def test_malformed_file_raises_file_load_error(malformed_file: Path) -> None:
    with pytest.raises(FileLoadError):
        load_csv(malformed_file)
