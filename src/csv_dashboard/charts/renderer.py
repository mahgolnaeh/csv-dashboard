import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from csv_dashboard.insights.chart_spec import ChartSpec

PLOTLY_TEMPLATE = "plotly_white"
COLORS = px.colors.qualitative.Safe


def render(spec: ChartSpec, df: pd.DataFrame) -> go.Figure:
    """Build a Plotly figure from a validated ChartSpec + query result."""
    ct   = spec.chart_type
    xcol = spec.x_column
    ycol = spec.y_column
    ccol = spec.color_column

    if spec.sort_order != "none" and ycol and ycol in df.columns:
        df = df.sort_values(ycol, ascending=(spec.sort_order == "asc"))

    if ct == "bar":
        fig = px.bar(
            df, x=xcol, y=ycol, color=ccol,
            labels={xcol: spec.x_label or xcol, ycol: spec.y_label or ycol},
            color_discrete_sequence=COLORS,
            template=PLOTLY_TEMPLATE,
        )

    elif ct == "line":
        fig = px.line(
            df, x=xcol, y=ycol, color=ccol,
            labels={xcol: spec.x_label or xcol, ycol: spec.y_label or ycol},
            template=PLOTLY_TEMPLATE,
        )

    elif ct == "scatter":
        # trendline="ols" omitted -- statsmodels is not in project deps
        fig = px.scatter(
            df, x=xcol, y=ycol, color=ccol,
            labels={xcol: spec.x_label or xcol, ycol: spec.y_label or ycol},
            template=PLOTLY_TEMPLATE,
        )

    elif ct == "histogram":
        fig = px.histogram(
            df, x=xcol,
            labels={xcol: spec.x_label or xcol},
            template=PLOTLY_TEMPLATE,
            nbins=30,
        )

    elif ct == "heatmap":
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        corr = df[numeric_cols].corr()
        fig = px.imshow(
            corr, color_continuous_scale="RdBu",
            zmin=-1, zmax=1, aspect="auto",
            template=PLOTLY_TEMPLATE,
        )

    else:
        fig = px.bar(df, x=xcol, y=ycol, template=PLOTLY_TEMPLATE)

    fig.update_layout(
        title=dict(text=spec.title, font=dict(size=16)),
        margin=dict(t=50, b=40, l=40, r=20),
        height=400,
    )

    if spec.plain_language_explanation:
        fig.add_annotation(
            text=spec.plain_language_explanation,
            xref="paper", yref="paper",
            x=0, y=-0.12, showarrow=False,
            font=dict(size=12, color="gray"),
            xanchor="left",
        )

    return fig
