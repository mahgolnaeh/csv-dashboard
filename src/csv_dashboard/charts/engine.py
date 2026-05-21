"""
chart_engine.py
---------------
Automatic chart selection engine for CSV files.
Designed for non-technical users and business consultants.

Rules applied:
  R01 - Numeric column        → histogram
  R02 - Numeric with outliers → histogram + outlier annotation (NOT boxplot)
  R03 - Categorical (low/medium cardinality) → bar chart of counts
  R04 - Numeric + categorical → bar chart of mean/median by category
  R05 - Two numeric, |r| > 0.4 → scatter plot with trend line
  R06 - Multiple numeric      → correlation heatmap (only |r| > 0.5 shown)
  R07 - Datetime column       → record count over time
  R08 - Datetime + numeric    → average numeric value over time
  R09 - Skip identifier columns
  R10 - Skip columns with > 40% missing  (unless it IS the missingness chart)
  R11 - High-cardinality categorical → top-N only (default N=10)
  R00 - Always produce a summary card first (rows, cols, key columns)
  R12 - Always produce a data-health (missingness) bar chart
"""

import re
from typing import Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy import stats

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TOP_N = 10                    # R11: max categories to show
MISSING_THRESHOLD = 0.40      # R10: skip columns above this fraction missing
CORRELATION_THRESHOLD = 0.40  # R05: minimum |r| for scatter plot
HEATMAP_THRESHOLD = 0.50      # R06: only show pairs above this in heatmap
IQR_MULTIPLIER = 1.5          # R02: outlier detection multiplier
MAX_CARDINALITY_BAR = 20      # R03/R04: "low/medium" cardinality ceiling
MAX_R04_PER_CAT = 2           # R04: max numerics per categorical in priority section
MAX_R08_PER_DT = 2            # R08: max numerics per datetime in priority section

# Patterns that suggest a column is an identifier (R09)
IDENTIFIER_PATTERNS = [
    r"^id$", r"_id$", r"^uuid", r"^index$", r"^row_?num",
    r"^key$", r"^record_?id", r"^pk$"
]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _is_identifier(col: str, series: pd.Series) -> bool:
    """R09: detect identifier columns by name pattern or near-unique values."""
    col_lower = col.lower().strip()
    for pattern in IDENTIFIER_PATTERNS:
        if re.search(pattern, col_lower):
            return True
    # Also flag if numeric but almost all values are unique (like auto-increment IDs)
    if pd.api.types.is_integer_dtype(series):
        if series.nunique() / max(len(series.dropna()), 1) > 0.95:
            return True
    return False


def _missing_fraction(series: pd.Series) -> float:
    return series.isna().mean()


def _has_outliers(series: pd.Series) -> bool:
    """R02: IQR-based outlier check."""
    clean = series.dropna()
    if len(clean) < 4:
        return False
    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - IQR_MULTIPLIER * iqr
    upper = q3 + IQR_MULTIPLIER * iqr
    return bool(((clean < lower) | (clean > upper)).any())


def _outlier_bounds(series: pd.Series):
    clean = series.dropna()
    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    iqr = q3 - q1
    return q1 - IQR_MULTIPLIER * iqr, q3 + IQR_MULTIPLIER * iqr


def _infer_datetime(df: pd.DataFrame) -> list[str]:
    """Return column names that look like datetime."""
    dt_cols = []
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            dt_cols.append(col)
        elif pd.api.types.is_string_dtype(df[col]) and not pd.api.types.is_numeric_dtype(df[col]):
            # pandas 3.x returns VARCHAR as StringDtype ("str"), not object
            sample = df[col].dropna().head(50)
            try:
                parsed = pd.to_datetime(sample, format="mixed", errors="coerce")
                if parsed.notna().mean() >= 0.8:
                    dt_cols.append(col)
            except Exception:
                pass
    return dt_cols


def _safe_to_datetime(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(series, errors="coerce")
    except Exception:
        return series


def _chart_colors():
    """Consistent color palette."""
    return px.colors.qualitative.Safe


PLOTLY_TEMPLATE = "plotly_white"


# ─────────────────────────────────────────────
# CHART BUILDERS
# ─────────────────────────────────────────────

def chart_summary_card(df: pd.DataFrame, filename: str = "") -> go.Figure:
    """R00: Summary card — rows, columns, key column names."""
    rows, cols = df.shape
    col_types = df.dtypes.value_counts().to_dict()
    type_summary = ", ".join(f"{v} {k}" for k, v in col_types.items())

    col_names = "<br>".join(
        [f"• {c} ({df[c].dtype})" for c in df.columns[:20]]
        + (["• ..."] if len(df.columns) > 20 else [])
    )

    fig = go.Figure()
    fig.add_annotation(
        x=0.5, y=0.85, xref="paper", yref="paper",
        text=f"<b>{filename or 'Dataset overview'}</b>",
        showarrow=False, font=dict(size=20)
    )
    fig.add_annotation(
        x=0.5, y=0.65, xref="paper", yref="paper",
        text=f"<b>{rows:,}</b> rows &nbsp;·&nbsp; <b>{cols}</b> columns",
        showarrow=False, font=dict(size=16)
    )
    fig.add_annotation(
        x=0.5, y=0.50, xref="paper", yref="paper",
        text=f"Column types: {type_summary}",
        showarrow=False, font=dict(size=13), font_color="gray"
    )
    fig.add_annotation(
        x=0.1, y=0.30, xref="paper", yref="paper",
        text=col_names,
        showarrow=False, font=dict(size=12), align="left",
        xanchor="left"
    )
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title="Dataset summary",
        height=400,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False)
    )
    return fig


def chart_missingness(df: pd.DataFrame) -> Optional[go.Figure]:
    """R12: Always show a missing-data bar chart."""
    missing = (df.isna().mean() * 100).sort_values(ascending=False)
    missing = missing[missing > 0]
    if missing.empty:
        return None  # No missing data — skip

    colors = ["#e74c3c" if v > 40 else "#f39c12" if v > 10 else "#95a5a6"
              for v in missing.values]

    fig = go.Figure(go.Bar(
        x=missing.index.tolist(),
        y=missing.values,
        marker_color=colors,
        text=[f"{v:.1f}%" for v in missing.values],
        textposition="outside"
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title="Data health — missing values per column",
        xaxis_title="Column",
        yaxis_title="Missing (%)",
        yaxis=dict(range=[0, 110]),
        height=350
    )
    fig.add_hline(y=40, line_dash="dash", line_color="red",
                  annotation_text="40% threshold (R10)",
                  annotation_position="top right")
    return fig


def chart_histogram(col: str, series: pd.Series, show_outliers: bool = False) -> go.Figure:
    """R01 + R02: Histogram, with optional outlier zone annotation."""
    clean = series.dropna()
    fig = go.Figure(go.Histogram(
        x=clean,
        nbinsx=30,
        marker_color="#3498db",
        opacity=0.85,
        name=col
    ))

    if show_outliers:
        lower, upper = _outlier_bounds(series)
        for bound, label in [(lower, "Lower outlier zone"), (upper, "Upper outlier zone")]:
            fig.add_vline(
                x=bound, line_dash="dash", line_color="#e74c3c",
                annotation_text=label, annotation_position="top"
            )

    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=f"Distribution of '{col}'" + (" (outliers marked)" if show_outliers else ""),
        xaxis_title=col,
        yaxis_title="Count",
        height=350
    )
    return fig


def chart_bar_counts(col: str, series: pd.Series) -> go.Figure:
    """R03: Bar chart of value counts. Top-N for high cardinality (R11)."""
    counts = series.value_counts()
    if len(counts) > TOP_N:
        counts = counts.head(TOP_N)
        title_suffix = f" (top {TOP_N} shown)"
    else:
        title_suffix = ""

    fig = go.Figure(go.Bar(
        x=counts.index.astype(str).tolist(),
        y=counts.values.tolist(),
        marker_color="#2ecc71",
        text=counts.values.tolist(),
        textposition="outside"
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=f"Count of '{col}'{title_suffix}",
        xaxis_title=col,
        yaxis_title="Count",
        height=350
    )
    return fig


def chart_bar_by_category(
    num_col: str, cat_col: str,
    num_series: pd.Series, cat_series: pd.Series,
    use_median: bool = False
) -> go.Figure:
    """R04: Average or median numeric value grouped by category."""
    agg_fn = "median" if use_median else "mean"
    df_tmp = pd.DataFrame({num_col: num_series, cat_col: cat_series}).dropna()
    grouped = df_tmp.groupby(cat_col)[num_col].agg(agg_fn).sort_values(ascending=False)

    if len(grouped) > TOP_N:
        grouped = grouped.head(TOP_N)
        title_suffix = f" (top {TOP_N} categories)"
    else:
        title_suffix = ""

    label = "Median" if use_median else "Mean"
    fig = go.Figure(go.Bar(
        x=grouped.index.astype(str).tolist(),
        y=grouped.values.tolist(),
        marker_color="#9b59b6",
        text=[f"{v:.2f}" for v in grouped.values],
        textposition="outside"
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=f"{label} '{num_col}' by '{cat_col}'{title_suffix}",
        xaxis_title=cat_col,
        yaxis_title=f"{label} {num_col}",
        height=350
    )
    return fig


def chart_scatter(col_x: str, col_y: str, series_x: pd.Series, series_y: pd.Series) -> go.Figure:
    """R05: Scatter plot with trend line. Only called when |r| > CORRELATION_THRESHOLD."""
    df_tmp = pd.DataFrame({col_x: series_x, col_y: series_y}).dropna()
    r, p = stats.pearsonr(df_tmp[col_x], df_tmp[col_y])

    # Trend line
    slope, intercept, *_ = stats.linregress(df_tmp[col_x], df_tmp[col_y])
    x_range = np.linspace(df_tmp[col_x].min(), df_tmp[col_x].max(), 100)
    y_trend = slope * x_range + intercept

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_tmp[col_x].tolist(), y=df_tmp[col_y].tolist(),
        mode="markers",
        marker=dict(color="#e67e22", opacity=0.6, size=6),
        name="Data points"
    ))
    fig.add_trace(go.Scatter(
        x=x_range.tolist(), y=y_trend.tolist(),
        mode="lines",
        line=dict(color="#c0392b", width=2, dash="dash"),
        name=f"Trend (r={r:.2f})"
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=f"'{col_x}' vs '{col_y}'  |  r = {r:.2f}, p = {p:.3f}",
        xaxis_title=col_x,
        yaxis_title=col_y,
        height=400
    )
    return fig


def chart_correlation_heatmap(numeric_df: pd.DataFrame) -> Optional[go.Figure]:
    """R06: Correlation heatmap. Only shows pairs with |r| > HEATMAP_THRESHOLD."""
    corr = numeric_df.corr()
    # Mask weak correlations
    mask = corr.abs() < HEATMAP_THRESHOLD
    display_corr = corr.copy()
    display_corr[mask] = np.nan

    if display_corr.isna().all(axis=None):
        return None  # Nothing strong enough to show

    fig = go.Figure(go.Heatmap(
        z=display_corr.values.tolist(),
        x=display_corr.columns.tolist(),
        y=display_corr.columns.tolist(),
        colorscale="RdBu",
        zmid=0,
        zmin=-1, zmax=1,
        text=[[f"{v:.2f}" if not np.isnan(v) else "" for v in row]
              for row in display_corr.values],
        texttemplate="%{text}",
        colorbar=dict(
            title="Correlation",
            tickvals=[-1, -0.5, 0, 0.5, 1],
            ticktext=["−1 (strong negative)", "−0.5", "0", "+0.5", "+1 (strong positive)"]
        )
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=f"Correlation heatmap (only |r| > {HEATMAP_THRESHOLD} shown)",
        height=max(350, 60 * len(corr.columns))
    )
    return fig


def chart_records_over_time(dt_col: str, dt_series: pd.Series) -> go.Figure:
    """R07: Record count over time."""
    dt = _safe_to_datetime(dt_series).dropna()
    # Auto-choose time frequency
    span_days = (dt.max() - dt.min()).days
    if span_days > 365 * 2:
        freq, label = "M", "month"  # to_period() uses "M", not "ME"
    elif span_days > 60:
        freq, label = "W", "week"
    else:
        freq, label = "D", "day"

    counts = dt.groupby(dt.dt.to_period(freq)).count()
    counts.index = counts.index.to_timestamp()

    fig = go.Figure(go.Scatter(
        x=counts.index.tolist(),
        y=counts.values.tolist(),
        mode="lines+markers",
        line=dict(color="#1abc9c", width=2),
        marker=dict(size=4)
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=f"Records over time (by {label})",
        xaxis_title="Date",
        yaxis_title="Count",
        height=350
    )
    return fig


def chart_avg_over_time(
    dt_col: str, num_col: str,
    dt_series: pd.Series, num_series: pd.Series
) -> go.Figure:
    """R08: Average numeric value over time."""
    df_tmp = pd.DataFrame({"dt": _safe_to_datetime(dt_series), "val": num_series}).dropna()
    span_days = (df_tmp["dt"].max() - df_tmp["dt"].min()).days
    if span_days > 365 * 2:
        freq, label = "M", "month"  # to_period() uses "M", not "ME"
    elif span_days > 60:
        freq, label = "W", "week"
    else:
        freq, label = "D", "day"

    df_tmp["period"] = df_tmp["dt"].dt.to_period(freq).dt.to_timestamp()
    avg = df_tmp.groupby("period")["val"].mean().reset_index()

    fig = go.Figure(go.Scatter(
        x=avg["period"].tolist(),
        y=avg["val"].tolist(),
        mode="lines+markers",
        line=dict(color="#e74c3c", width=2),
        marker=dict(size=4),
        fill="tozeroy",
        fillcolor="rgba(231,76,60,0.08)"
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=f"Average '{num_col}' over time (by {label})",
        xaxis_title="Date",
        yaxis_title=f"Mean {num_col}",
        height=350
    )
    return fig


# ─────────────────────────────────────────────
# MAIN ENGINE
# ─────────────────────────────────────────────

def generate_charts(
    df: pd.DataFrame,
    filename: str = "",
    max_charts: int | None = 6,
) -> list[dict]:
    """
    Main entry point.
    Returns a list of dicts: {"title": str, "figure": go.Figure, "rule": str}

    max_charts: cap for fallback mode (default 6 — meaningful charts for a non-technical
                user). Pass None for pool mode (all possible charts, ordered by priority).

    Charts are generated in priority order so that truncation always keeps the
    most informative charts:
        P1  R00 / R12   — summary + data health (always)
        P2  R07         — temporal trends
        P3  R03         — low-cardinality categorical counts
        P4  R08         — avg numeric over time (top-N numerics only)
        P5  R01 / R02   — numeric distributions (outlier cols first)
        P6  R04         — numeric × categorical (low-cardinality cats, top-N numerics)
        P7  R05         — strongest correlation scatter only
        P8  R06         — correlation heatmap
        Pool            — remaining combinations (high-cardinality, extra pairs)
    """
    charts: list[dict] = []
    scatter_done: set[tuple[str, str]] = set()

    def add(title: str, fig: go.Figure, rule: str) -> None:
        if fig is not None:
            charts.append({"title": title, "figure": fig, "rule": rule})

    def _col_std(col: str) -> float:
        try:
            return float(df[col].std())
        except Exception:
            return 0.0

    # ── Column classification (R09, R10) ─────────────────────────────
    dt_cols = _infer_datetime(df)
    numeric_cols: list[str] = []
    categorical_cols: list[str] = []

    for col in df.columns:
        series = df[col]
        if _is_identifier(col, series):
            continue
        if col not in dt_cols and _missing_fraction(series) > MISSING_THRESHOLD:
            continue
        if col in dt_cols:
            continue
        if pd.api.types.is_numeric_dtype(series):
            numeric_cols.append(col)
        elif pd.api.types.is_string_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype):
            categorical_cols.append(col)

    # Numerics ordered by descending std (most variable = most interesting first)
    numeric_by_interest = sorted(numeric_cols, key=_col_std, reverse=True)

    # "Useful" categoricals: low enough cardinality for readable bar charts and R04
    useful_cat_cols = [c for c in categorical_cols if df[c].nunique() <= MAX_CARDINALITY_BAR]

    # ── P1: Summary and data health ───────────────────────────────────
    add("Dataset summary", chart_summary_card(df, filename), "R00")
    add("Data health — missing values", chart_missingness(df), "R12")

    # ── P2: Temporal trends (R07) ─────────────────────────────────────
    for dt_col in dt_cols:
        if _missing_fraction(df[dt_col]) > MISSING_THRESHOLD:
            continue
        add(
            f"Records over time: {dt_col}",
            chart_records_over_time(dt_col, df[dt_col]),
            "R07",
        )

    # ── P3: Low-cardinality categorical counts (R03) ──────────────────
    for col in useful_cat_cols:
        add(f"Count of '{col}'", chart_bar_counts(col, df[col]), "R03")

    # ── P4: Average of top-N numerics over time (R08) ─────────────────
    for dt_col in dt_cols:
        if _missing_fraction(df[dt_col]) > MISSING_THRESHOLD:
            continue
        for num_col in numeric_by_interest[:MAX_R08_PER_DT]:
            add(
                f"Average '{num_col}' over time",
                chart_avg_over_time(dt_col, num_col, df[dt_col], df[num_col]),
                "R08",
            )

    # ── P5: Numeric distributions — outlier cols first, then by std ───
    numeric_by_hist = sorted(
        numeric_cols,
        key=lambda c: (0 if _has_outliers(df[c]) else 1, -_col_std(c)),
    )
    for col in numeric_by_hist:
        has_out = _has_outliers(df[col])
        add(
            f"Distribution: {col}",
            chart_histogram(col, df[col], show_outliers=has_out),
            "R02" if has_out else "R01",
        )

    # ── P6: Best numeric × categorical pairs (R04) ────────────────────
    # Restricted to useful (low-cardinality) categoricals × top-N numerics.
    for cat_col in useful_cat_cols:
        if df[cat_col].nunique() < 2:
            continue
        for num_col in numeric_by_interest[:MAX_R04_PER_CAT]:
            use_median = _has_outliers(df[num_col])
            add(
                f"'{num_col}' by '{cat_col}'",
                chart_bar_by_category(num_col, cat_col, df[num_col], df[cat_col], use_median),
                "R04",
            )

    # ── P7: Strongest correlation only (R05) ──────────────────────────
    if len(numeric_cols) >= 2:
        best_pair: tuple[str, str] | None = None
        best_r = 0.0
        for i, cx in enumerate(numeric_cols):
            for cy in numeric_cols[i + 1:]:
                df_pair = df[[cx, cy]].dropna()
                if len(df_pair) < 10:
                    continue
                r, _ = stats.pearsonr(df_pair[cx], df_pair[cy])
                if abs(r) >= CORRELATION_THRESHOLD and abs(r) > best_r:
                    best_r = abs(r)
                    best_pair = (cx, cy)
        if best_pair:
            cx, cy = best_pair
            scatter_done.add((min(cx, cy), max(cx, cy)))
            add(f"Scatter: {cx} vs {cy}", chart_scatter(cx, cy, df[cx], df[cy]), "R05")

    # ── P8: Correlation heatmap (R06) ─────────────────────────────────
    if len(numeric_cols) >= 3:
        num_df = df[numeric_cols].dropna()
        if len(num_df) >= 5:
            add("Correlation heatmap", chart_correlation_heatmap(num_df), "R06")

    # ── POOL: remaining charts (visible only when max_charts=None) ─────

    # R11: high-cardinality categoricals (top-N bar)
    for col in categorical_cols:
        if col in useful_cat_cols:
            continue
        add(f"Counts: {col} (top {TOP_N})", chart_bar_counts(col, df[col]), "R11")

    # R04 pool: remaining numerics for useful categoricals
    for cat_col in useful_cat_cols:
        if df[cat_col].nunique() < 2:
            continue
        for num_col in numeric_by_interest[MAX_R04_PER_CAT:]:
            use_median = _has_outliers(df[num_col])
            add(
                f"'{num_col}' by '{cat_col}'",
                chart_bar_by_category(num_col, cat_col, df[num_col], df[cat_col], use_median),
                "R04",
            )

    # R04 pool: high-cardinality categoricals × all numerics
    for cat_col in categorical_cols:
        if cat_col in useful_cat_cols or df[cat_col].nunique() < 2:
            continue
        for num_col in numeric_by_interest:
            use_median = _has_outliers(df[num_col])
            add(
                f"'{num_col}' by '{cat_col}' (top {TOP_N})",
                chart_bar_by_category(num_col, cat_col, df[num_col], df[cat_col], use_median),
                "R04",
            )

    # R08 pool: additional numerics over time
    for dt_col in dt_cols:
        if _missing_fraction(df[dt_col]) > MISSING_THRESHOLD:
            continue
        for num_col in numeric_by_interest[MAX_R08_PER_DT:]:
            add(
                f"Average '{num_col}' over time",
                chart_avg_over_time(dt_col, num_col, df[dt_col], df[num_col]),
                "R08",
            )

    # R05 pool: remaining correlated pairs
    if len(numeric_cols) >= 2:
        for i, cx in enumerate(numeric_cols):
            for cy in numeric_cols[i + 1:]:
                pair = (min(cx, cy), max(cx, cy))
                if pair in scatter_done:
                    continue
                df_pair = df[[cx, cy]].dropna()
                if len(df_pair) < 10:
                    continue
                r, _ = stats.pearsonr(df_pair[cx], df_pair[cy])
                if abs(r) >= CORRELATION_THRESHOLD:
                    scatter_done.add(pair)
                    add(f"Scatter: {cx} vs {cy}", chart_scatter(cx, cy, df[cx], df[cy]), "R05")

    return charts[:max_charts] if max_charts is not None else charts


# ─────────────────────────────────────────────
# CONVENIENCE: run from file path
# ─────────────────────────────────────────────

def run(csv_path: str, show: bool = True) -> list[dict]:
    """Load a CSV and generate all charts. Optionally open them in browser."""
    import os
    df = pd.read_csv(csv_path)
    filename = os.path.basename(csv_path)
    print(f"Loaded: {filename}  |  {df.shape[0]} rows × {df.shape[1]} cols")

    charts = generate_charts(df, filename)
    print(f"Generated {len(charts)} charts:")
    for i, c in enumerate(charts, 1):
        print(f"  {i:>2}. [{c['rule']}] {c['title']}")

    if show:
        for c in charts:
            c["figure"].show()

    return charts


# ─────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path:
        run(path)
    else:
        print("Usage: python chart_engine.py path/to/file.csv")
