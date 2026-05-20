"""
chart_spec.py
-------------
Pydantic models for LLM-generated chart specifications.

Three layers of protection:
  1. Type validation   — wrong types are caught immediately
  2. Value validation  — only allowed values (chart types, sort orders, etc.)
  3. Cross-field validation — rules that span multiple fields
     e.g. histogram must not have y_column
"""

from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator, field_validator
import re


# ── Allowed vocabularies ───────────────────────────────────────────────────────

ChartType = Literal["bar", "line", "scatter", "histogram", "heatmap", "box"]

AggregationType = Literal["COUNT", "AVG", "SUM", "MEDIAN", "MIN", "MAX", "NONE"]

SortOrder = Literal["asc", "desc", "none"]


# ── Main model ─────────────────────────────────────────────────────────────────

class ChartSpec(BaseModel):
    # ── Identity ───────────────────────────────────────────────────────────────
    title: str = Field(
        ...,
        min_length=3,
        max_length=80,
        description="Short human-readable chart title."
    )

    chart_type: ChartType = Field(
        ...,
        description="One of: bar, line, scatter, histogram, heatmap, box."
    )

    business_question: str = Field(
        ...,
        min_length=10,
        max_length=200,
        description="The business question this chart answers."
    )

    # ── Data ───────────────────────────────────────────────────────────────────
    sql_query: str = Field(
        ...,
        description="Valid DuckDB SELECT query. Table name must be 'data'."
    )

    x_column: Optional[str] = Field(
        default=None,
        description="Column name for x-axis. Null for heatmap."
    )

    y_column: Optional[str] = Field(
        default=None,
        description="Column name for y-axis. Null for histogram."
    )

    color_column: Optional[str] = Field(
        default=None,
        description="Column for color grouping. Null if not needed."
    )

    aggregation: AggregationType = Field(
        ...,
        description="Aggregation applied to y_column. NONE if raw values."
    )

    # ── Display ────────────────────────────────────────────────────────────────
    sort_order: SortOrder = Field(
        default="none",
        description="Sort bars/lines: asc, desc, or none (e.g. for time series)."
    )

    limit: Optional[int] = Field(
        default=10,
        ge=2,
        le=50,
        description="Max number of categories/rows to show. Prevents unreadable charts."
    )

    x_label: Optional[str] = Field(
        default=None,
        max_length=60,
        description="Human-readable x-axis label shown to the user."
    )

    y_label: Optional[str] = Field(
        default=None,
        max_length=60,
        description="Human-readable y-axis label shown to the user."
    )

    plain_language_explanation: str = Field(
        ...,
        min_length=20,
        max_length=300,
        description="One or two sentences explaining the chart to a non-technical user."
    )

    # ── Field-level validators ─────────────────────────────────────────────────

    @field_validator("sql_query")
    @classmethod
    def sql_must_be_select(cls, v: str) -> str:
        """Reject anything that is not a SELECT — safety against INSERT/DROP etc."""
        clean = v.strip().upper()
        if not clean.startswith("SELECT"):
            raise ValueError("sql_query must start with SELECT.")
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"]
        for word in forbidden:
            if re.search(rf"\b{word}\b", clean):
                raise ValueError(f"sql_query must not contain {word}.")
        return v

    @field_validator("sql_query")
    @classmethod
    def sql_must_reference_data_table(cls, v: str) -> str:
        """Make sure the query uses the correct table name."""
        if "FROM CLEANED_DATA" not in v.upper() and "FROM DATA" not in v.upper():
            raise ValueError("sql_query must reference table 'cleaned_data' (FROM cleaned_data).")
        return v

    # ── Cross-field validators ─────────────────────────────────────────────────

    @model_validator(mode="after")
    def check_histogram_has_no_y(self) -> ChartSpec:
        """Histogram only needs x_column. y_column makes no sense."""
        if self.chart_type == "histogram" and self.y_column is not None:
            raise ValueError("histogram does not use y_column. Set y_column to null.")
        return self

    @model_validator(mode="after")
    def check_histogram_has_x(self) -> ChartSpec:
        if self.chart_type == "histogram" and self.x_column is None:
            raise ValueError("histogram requires x_column.")
        return self

    @model_validator(mode="after")
    def check_scatter_has_both_axes(self) -> ChartSpec:
        if self.chart_type == "scatter":
            if self.x_column is None or self.y_column is None:
                raise ValueError("scatter requires both x_column and y_column.")
        return self

    @model_validator(mode="after")
    def check_heatmap_has_no_axes(self) -> ChartSpec:
        """Heatmap uses a list of columns internally, not x/y."""
        if self.chart_type == "heatmap":
            if self.x_column is not None or self.y_column is not None:
                raise ValueError(
                    "heatmap does not use x_column or y_column. Set both to null."
                )
        return self

    @model_validator(mode="after")
    def check_aggregation_none_for_raw_charts(self) -> ChartSpec:
        """
        Scatter and histogram usually work on raw values.
        Warn if aggregation is set — likely a mistake.
        """
        if self.chart_type in ("scatter", "histogram") and self.aggregation != "NONE":
            raise ValueError(
                f"{self.chart_type} usually has aggregation=NONE. "
                f"Got {self.aggregation}. If intentional, reconsider the chart type."
            )
        return self

    @model_validator(mode="after")
    def check_bar_line_have_aggregation(self) -> ChartSpec:
        """Bar and line charts almost always aggregate. Flag NONE as suspicious."""
        if self.chart_type in ("bar", "line") and self.aggregation == "NONE":
            raise ValueError(
                f"{self.chart_type} chart has aggregation=NONE. "
                "Did you mean COUNT or AVG? If raw values are intended, "
                "make sure your SQL already aggregates."
            )
        return self

    @model_validator(mode="after")
    def check_time_series_sort(self) -> ChartSpec:
        """Line charts over time should not be sorted asc/desc — order is chronological."""
        if self.chart_type == "line" and self.sort_order in ("asc", "desc"):
            raise ValueError(
                "line charts (time series) should have sort_order='none'. "
                "Chronological order comes from the datetime column, not sorting."
            )
        return self


# ── Wrapper: full LLM response ─────────────────────────────────────────────────

class ChartSpecList(BaseModel):
    """The full JSON the LLM returns: a list of 3–5 chart specs."""

    charts: list[ChartSpec] = Field(
        ...,
        min_length=3,
        max_length=5,
        description="Between 3 and 5 chart specs."
    )


# ── Quick demo ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from pydantic import ValidationError

    print("=== Valid spec ===")
    valid = ChartSpec(
        title="Average price by room type",
        chart_type="bar",
        business_question="Which room type is most expensive on average?",
        sql_query="SELECT room_type, AVG(price) AS avg_price FROM cleaned_data GROUP BY room_type ORDER BY avg_price DESC LIMIT 10",
        x_column="room_type",
        y_column="avg_price",
        color_column=None,
        aggregation="AVG",
        sort_order="desc",
        limit=10,
        x_label="Room type",
        y_label="Average price (USD)",
        plain_language_explanation="Shows which listing type costs the most on average."
    )
    print("OK:", valid.title)

    print("\n=== Invalid: histogram with y_column ===")
    try:
        ChartSpec(
            title="Price distribution",
            chart_type="histogram",
            business_question="How is price distributed?",
            sql_query="SELECT price FROM cleaned_data",
            x_column="price",
            y_column="room_type",   # <-- wrong
            aggregation="NONE",
            sort_order="none",
            plain_language_explanation="Shows the spread of prices across all listings."
        )
    except ValidationError as e:
        print("Caught:", e.errors()[0]["msg"])

    print("\n=== Invalid: SQL with DROP ===")
    try:
        ChartSpec(
            title="Danger",
            chart_type="bar",
            business_question="Something",
            sql_query="DROP TABLE data",
            x_column="x",
            y_column="y",
            aggregation="COUNT",
            sort_order="desc",
            plain_language_explanation="This should not pass validation at all."
        )
    except ValidationError as e:
        print("Caught:", e.errors()[0]["msg"])

    print("\n=== Invalid: bar chart with aggregation=NONE ===")
    try:
        ChartSpec(
            title="Counts",
            chart_type="bar",
            business_question="Something",
            sql_query="SELECT room_type, price FROM cleaned_data",
            x_column="room_type",
            y_column="price",
            aggregation="NONE",   # <-- suspicious for bar chart
            sort_order="desc",
            plain_language_explanation="A bar chart with raw values — likely a mistake."
        )
    except ValidationError as e:
        print("Caught:", e.errors()[0]["msg"])
