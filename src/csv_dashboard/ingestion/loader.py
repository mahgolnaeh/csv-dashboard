import duckdb
from pathlib import Path


class FileLoadError(Exception):
    """Raised when a CSV cannot be loaded."""


def load_csv(path: str | Path) -> duckdb.DuckDBPyConnection:
    """Load a CSV into DuckDB as table 'raw_data'."""
    path_str = str(path)
    try:
        con = duckdb.connect()
        con.execute(
            "CREATE OR REPLACE TABLE raw_data AS "
            f"SELECT * FROM read_csv_auto('{path_str}', header=true)"
        )
        return con
    except Exception as e:
        raise FileLoadError(f"Could not load CSV: {e}") from e
