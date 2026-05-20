"""
transparency.py
---------------
Converts quality_report from data_quality.py into plain-language
sentences for non-technical users.

One sentence per change. No jargon. No technical details.
The user just needs to know: "what happened to my data?"
"""

from __future__ import annotations
import re


# ── Message templates — plain English, no technical terms ─────────────────────

def _to_sentence(entry: dict) -> str | None:
    sev   = entry["severity"]
    col   = entry.get("column", "")
    issue = entry["issue"]
    detail = entry.get("detail", "")

    col_part = f'Column "{col}": ' if col else ""

    # ── Dropped ───────────────────────────────────────────────────────────────
    if sev == "drop":
        if "all-null" in issue:
            return f"{col_part}No data found. Removed from analysis."
        if "constant" in issue:
            return f"{col_part}Every row had the same value. Removed from analysis."
        if "duplicate column" in issue:
            return f"{col_part}Duplicate of another column. Removed."

    # ── Fixed ─────────────────────────────────────────────────────────────────
    if sev == "info":
        if "currency" in issue:
            return f"{col_part}Currency symbols removed. Values converted to numbers."
        if "sentinel null" in issue:
            count = _first_number(detail)
            who = f"{count} values" if count else "Some values"
            return f'{col_part}{who} like "N/A" or "unknown" treated as empty.'
        if "numeric strings" in issue:
            return f"{col_part}Numbers were stored as text. Converted to numeric."
        if "datetime" in issue:
            return f"{col_part}Date text converted to proper date format."
        if "column names normalized" in issue:
            return None   # not meaningful for end users
        if "duplicate column removed" in issue:
            return f"{col_part}Duplicate column removed."

    # ── Warning ───────────────────────────────────────────────────────────────
    if sev == "warn":
        if "outlier" in issue:
            count = _first_number(detail)
            who = f"{count} value(s)" if count else "Some values"
            return f"{col_part}{who} are unusually high or low. Shown as-is in charts."
        if "mixed types" in issue:
            return f"{col_part}Contains both numbers and text. Used as text only."
        if "inconsistent date" in issue:
            return f"{col_part}Date formats are not consistent. Time charts may not work."
        if "duplicate rows" in issue:
            count = _first_number(detail)
            who = f"{count} duplicate rows" if count else "Duplicate rows"
            return f"{who} found in the data. Kept as-is."
        if "high missing" in issue:
            pct = _first_percent(detail)
            how_much = f"{pct} of values" if pct else "Many values"
            return f"{col_part}{how_much} are empty. Charts may be incomplete."

    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def build(quality_report: list[dict]) -> dict:
    """
    Convert quality_report to plain-language sentences for the user.

    Returns:
        {
            "has_changes": bool,
            "sentences":   list[str],
            "plain_text":  str,
        }
    """
    sentences = [
        s for entry in quality_report
        if (s := _to_sentence(entry)) is not None
    ]
    return {
        "has_changes": len(sentences) > 0,
        "sentences":   sentences,
        "plain_text":  _format(sentences),
    }


def show_in_streamlit(quality_report: list[dict]) -> None:
    """
    Ready-to-use Streamlit block.

    Usage:
        from transparency import show_in_streamlit
        show_in_streamlit(dq["quality_report"])
    """
    try:
        import streamlit as st
    except ImportError:
        print(build(quality_report)["plain_text"])
        return

    result = build(quality_report)
    if not result["has_changes"]:
        st.info("Your data looks clean. No changes were needed.")
        return

    buckets: dict[str, list[str]] = {"drop": [], "warn": [], "info": []}
    for entry in quality_report:
        s = _to_sentence(entry)
        if s:
            buckets[entry["severity"]].append(s)

    with st.expander("What we did to prepare your data", expanded=True):
        for s in buckets["drop"]:
            st.error(f"Removed  —  {s}")
        for s in buckets["warn"]:
            st.warning(f"Note  —  {s}")
        for s in buckets["info"]:
            st.success(f"Fixed  —  {s}")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format(sentences: list[str]) -> str:
    if not sentences:
        return "Your data looks clean. No changes were needed."
    lines = ["While preparing your data, the following changes were made:\n"]
    lines += [f"  - {s}" for s in sentences]
    return "\n".join(lines)


def _first_number(text: str) -> str:
    m = re.search(r"\b(\d+)\b", text)
    return m.group(1) if m else ""


def _first_percent(text: str) -> str:
    m = re.search(r"(\d+)%", text)
    return f"{m.group(1)}%" if m else ""


# ── Quick test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    import duckdb, pandas as pd, numpy as np, data_quality

    np.random.seed(42)
    n = 100
    df = pd.DataFrame({
        "id":        range(n),
        "price":     ["$" + str(int(x)) for x in np.random.normal(150, 40, n)],
        "room_type": np.random.choice(["Entire home", "Private room"], n),
        "score":     np.random.normal(4.5, 0.5, n),
        "reviews":   ["N/A" if i % 10 == 0 else str(i) for i in range(n)],
        "created":   pd.date_range("2023-01-01", periods=n, freq="D").astype(str),
        "empty":     [None] * n,
        "constant":  ["NYC"] * n,
    })
    df.loc[0, "score"] = 99999

    con = duckdb.connect()
    con.register("raw_data", df)
    dq = data_quality.run(con, raw_table="raw_data")

    result = build(dq["quality_report"])
    print(result["plain_text"])
