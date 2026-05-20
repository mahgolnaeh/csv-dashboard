"""
Streamlit UI for CSV Dashboard.

Entry point: streamlit run src/csv_dashboard/ui/app.py

Structure:
- _bytes_to_result: pure testable function (bytes -> temp file -> pipeline -> cleanup)
- cached_run: st.cache_data wrapper keyed on file bytes (kept for test compatibility)
- _run_with_status: pipeline call with Streamlit progress callbacks via on_step
- _main: all Streamlit UI code (guarded from test imports)
"""

import hashlib
import sys
import tempfile
from pathlib import Path

import streamlit as st

from csv_dashboard.ingestion.loader import FileLoadError
from csv_dashboard.orchestrator import pipeline as _pipeline
from csv_dashboard.orchestrator.pipeline import PipelineResult


def _bytes_to_result(file_bytes: bytes, filename: str) -> PipelineResult:
    """Write bytes to a temp CSV, run pipeline, clean up, return result."""
    suffix = Path(filename).suffix or ".csv"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        return _pipeline.run(tmp_path)
    finally:
        if tmp_path:
            path = Path(tmp_path)
            if path.exists():
                path.unlink()


cached_run = st.cache_data(show_spinner=False)(_bytes_to_result)


def _run_with_status(file_bytes: bytes, filename: str) -> PipelineResult:
    """Write bytes to a temp CSV, run pipeline with progress callbacks, clean up."""
    suffix = Path(filename).suffix or ".csv"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        return _pipeline.run(tmp_path, on_step=st.write)
    finally:
        if tmp_path:
            path = Path(tmp_path)
            if path.exists():
                path.unlink()


def _main() -> None:
    st.set_page_config(page_title="CSV Dashboard", page_icon="📊", layout="wide")

    st.title("📊 CSV Dashboard")
    st.caption("Upload a CSV. Get insights. No setup needed.")

    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0

    uploaded = st.file_uploader(
        "Upload CSV",
        type=["csv"],
        label_visibility="collapsed",
        key=f"uploader_{st.session_state.uploader_key}",
    )

    if not uploaded:
        return

    # File size guard
    size_mb = uploaded.size / (1024 * 1024)
    if size_mb > 100:
        st.error("File exceeds 100 MB limit.")
        st.stop()
    if size_mb > 50:
        st.warning(f"File is {size_mb:.0f} MB. Analysis may take up to a minute.")

    file_bytes = uploaded.read()
    filename = uploaded.name
    file_hash = hashlib.md5(file_bytes).hexdigest()

    # Run pipeline (session-state cached by file content hash)
    if file_hash not in st.session_state:
        try:
            with st.status("Analyzing your data...", expanded=True) as status:
                result = _run_with_status(file_bytes, filename)
                status.update(label="Done!", state="complete", expanded=False)
            st.session_state[file_hash] = result
        except FileLoadError as exc:
            st.error(f"Could not read this file: {exc}")
            return
        except Exception as exc:
            with st.expander("Something went wrong", expanded=False):
                st.error(str(exc))
            return

    result: PipelineResult = st.session_state.get(file_hash)
    if result is None:
        return

    if st.button("Upload a different file"):
        current_key = st.session_state.get("uploader_key", 0)
        st.session_state.clear()
        st.session_state.uploader_key = current_key + 1
        st.rerun()

    # ── Dataset summary card ──────────────────────────────────────────────────
    profile = result.profile
    n_quality_issues = len(result.transparency.get("sentences", []))

    col1, col2, col3 = st.columns(3)
    col1.metric("Rows", f"{profile.get('row_count', 0):,}")
    col2.metric("Columns", profile.get("column_count", 0))
    col3.metric("Quality issues", n_quality_issues)

    # ── Data preparation section ──────────────────────────────────────────────
    if n_quality_issues > 0:
        label = f"📋 What we did to prepare your data ({n_quality_issues} changes)"
        with st.expander(label, expanded=False):
            for sentence in result.transparency["sentences"]:
                st.write(f"- {sentence}")
    else:
        st.info("Your data was clean -- no preparation needed.")

    # ── Key insights ──────────────────────────────────────────────────────────
    st.markdown("### Key insights")
    if result.insights:
        for insight in result.insights:
            # Escape chars that Streamlit markdown treats as code formatting
            safe = insight.replace("`", r"\`").replace("$", r"\$")
            st.markdown(f"- {safe}")
    else:
        st.caption("No AI-generated insights available -- showing charts only.")

    # ── Charts grid ───────────────────────────────────────────────────────────
    st.markdown("### Charts")

    n_llm = sum(1 for c in result.charts if c.source == "llm")
    n_fallback = sum(1 for c in result.charts if c.source == "fallback")
    if n_fallback > 0 and n_llm == 0:
        st.caption("Using simplified chart generation (AI service unavailable).")
    elif n_fallback > 0:
        st.caption(f"{n_llm} AI-designed charts + {n_fallback} standard charts.")

    for i in range(0, len(result.charts), 2):
        col1, col2 = st.columns(2)
        cols = [col1, col2]
        for j, chart in enumerate(result.charts[i : i + 2]):
            with cols[j]:
                st.plotly_chart(chart.figure, use_container_width=True)
                if chart.source == "llm" and chart.explanation:
                    st.caption(f"💡 {chart.explanation}")
                else:
                    st.caption("📐 Standard chart")

    # ── Error banner ──────────────────────────────────────────────────────────
    if result.errors:
        with st.expander(f"⚠️ {len(result.errors)} warning(s)", expanded=False):
            for err in result.errors:
                st.warning(err)


if "pytest" not in sys.modules:
    _main()
