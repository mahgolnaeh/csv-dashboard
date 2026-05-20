"""
Tests for ui/app.py.

Focused on _bytes_to_result: the bytes-to-temp-file pipeline integration.
Streamlit widget rendering is not tested -- no Streamlit server in CI.

The sys.modules['streamlit'] override MUST happen before any import that
would load csv_dashboard.ui.app, so it appears at the very top of this file.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

# ── Streamlit mock ────────────────────────────────────────────────────────────
# Replaces streamlit with a MagicMock so that:
#   - @st.cache_data(show_spinner=False) becomes a pass-through decorator
#   - module-level st.* calls in app.py are silent no-ops
# Must be in place before csv_dashboard.ui.app is imported for the first time.
if "csv_dashboard.ui.app" not in sys.modules:
    _st_mock = MagicMock()
    _st_mock.cache_data = lambda **kwargs: (lambda func: func)
    sys.modules["streamlit"] = _st_mock

from csv_dashboard.ui.app import _bytes_to_result  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_CSV_BYTES = b"sex,age,fare\nfemale,29,100.0\nmale,30,50.0\n"


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_bytes_to_result_calls_pipeline_run_and_returns_result(mocker):
    """pipeline.run is called with a temp file path; its return value is passed through."""
    fake_result = MagicMock()
    mock_run = mocker.patch(
        "csv_dashboard.orchestrator.pipeline.run",
        return_value=fake_result,
    )

    result = _bytes_to_result(SAMPLE_CSV_BYTES, "test.csv")

    assert result is fake_result
    mock_run.assert_called_once()
    called_path = str(mock_run.call_args[0][0])
    assert called_path.endswith(".csv")


def test_bytes_to_result_deletes_temp_file_after_success(mocker):
    """Temp file is deleted from disk once pipeline.run completes successfully."""
    captured: list[str] = []

    def _capture_path(path):
        captured.append(str(path))
        return MagicMock()

    mocker.patch(
        "csv_dashboard.orchestrator.pipeline.run",
        side_effect=_capture_path,
    )

    _bytes_to_result(SAMPLE_CSV_BYTES, "test.csv")

    assert len(captured) == 1
    assert not os.path.exists(captured[0])


def test_bytes_to_result_deletes_temp_file_when_pipeline_raises(mocker):
    """Temp file is cleaned up even when pipeline.run raises an exception."""
    captured: list[str] = []

    def _capture_and_raise(path):
        captured.append(str(path))
        raise RuntimeError("pipeline failed")

    mocker.patch(
        "csv_dashboard.orchestrator.pipeline.run",
        side_effect=_capture_and_raise,
    )

    with pytest.raises(RuntimeError, match="pipeline failed"):
        _bytes_to_result(SAMPLE_CSV_BYTES, "test.csv")

    assert len(captured) == 1
    assert not os.path.exists(captured[0])


def test_bytes_to_result_writes_correct_content_to_temp_file(mocker):
    """The bytes passed in are the exact bytes written to the temp file."""
    content_seen: list[bytes] = []

    def _read_and_return(path):
        content_seen.append(open(path, "rb").read())
        return MagicMock()

    mocker.patch(
        "csv_dashboard.orchestrator.pipeline.run",
        side_effect=_read_and_return,
    )

    _bytes_to_result(SAMPLE_CSV_BYTES, "test.csv")

    assert content_seen == [SAMPLE_CSV_BYTES]


def test_bytes_to_result_preserves_filename_suffix(mocker):
    """Temp file suffix matches the suffix of the supplied filename."""
    captured: list[str] = []

    def _capture_path(path):
        captured.append(str(path))
        return MagicMock()

    mocker.patch(
        "csv_dashboard.orchestrator.pipeline.run",
        side_effect=_capture_path,
    )

    _bytes_to_result(SAMPLE_CSV_BYTES, "report.csv")

    assert len(captured) == 1
    assert captured[0].endswith(".csv")
