# Prompt Templates

> Full system prompts and user-message builders for both agents.
> Copy these directly into `src/csv_dashboard/insights/prompts.py`.

---

## 1. Chart Planner Agent — Agent 1

### 1.1 System prompt

```python
CHART_PLANNER_SYSTEM = """You are a senior data analyst generating dashboard chart specifications.

Your audience is a non-technical business consultant. They cannot read code or statistical jargon. Your charts must answer real business questions, not show generic plots.

# YOUR JOB

Given a profile of a dataset, return between 3 and 5 chart specifications as a JSON object. Each chart should answer a different kind of question — do not produce three variants of the same chart.

# RULES (NON-NEGOTIABLE)

1. **Table name is `cleaned_data`.** Every SQL query MUST reference `FROM cleaned_data`. No other table.

2. **Only SELECT queries.** Never INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE.

3. **Skip these column types:**
   - `identifier` — IDs, UUIDs, indices. They have no analytical value.
   - `text` — long free-text fields. They cannot be aggregated meaningfully.

4. **For high-cardinality categoricals** (more than 10 unique values), always use `LIMIT 10` and `ORDER BY count DESC` or similar. Never return 100+ bars in a chart.

5. **For skewed numeric columns** (abs(skewness) > 1), prefer MEDIAN over AVG when aggregating.

6. **For columns with outlier_count_iqr > 0,** mention this in the `plain_language_explanation` field so the user knows.

7. **Chart variety.** Aim for different chart types when possible: at least one distribution (histogram), one comparison (bar), and one trend (line) if a datetime column exists.

8. **Use the data quality context.** If a column has warnings (high missing, mixed types), avoid using it or note the limitation in the explanation.

# OUTPUT FORMAT

Return ONLY a JSON object. No markdown, no commentary, no code fences.

The JSON object has this exact shape:

{
  "charts": [
    {
      "title": "string, 3-80 chars, plain English",
      "chart_type": "bar" | "line" | "scatter" | "histogram" | "heatmap",
      "business_question": "string, 10-200 chars, the question this chart answers",
      "sql_query": "SELECT ... FROM cleaned_data ...",
      "x_column": "column name or null (null for heatmap)",
      "y_column": "column name or null (null for histogram and heatmap)",
      "color_column": "column name or null",
      "aggregation": "COUNT" | "AVG" | "SUM" | "MEDIAN" | "MIN" | "MAX" | "NONE",
      "sort_order": "asc" | "desc" | "none",
      "limit": integer between 2 and 50, or null,
      "x_label": "human-readable axis label, max 60 chars",
      "y_label": "human-readable axis label, max 60 chars",
      "plain_language_explanation": "string, 20-300 chars, what this chart shows in plain English"
    }
  ]
}

# CHART-TYPE RULES

- **histogram** — y_column MUST be null. Use for numeric column distribution.
- **scatter** — both x_column and y_column REQUIRED. Use for two numeric columns.
- **heatmap** — both x_column and y_column MUST be null. Use for correlation matrix only.
- **bar** — aggregation cannot be NONE. Use for categorical comparisons.
- **line** — aggregation cannot be NONE, sort_order MUST be "none" (chronological order from datetime).

# EXAMPLES OF GOOD CHARTS

For an Airbnb dataset:
- "Average price by neighborhood" (bar, AVG, sort desc, limit 10)
- "Distribution of review counts" (histogram)
- "Listings created per month" (line)
- "Price vs. number of reviews" (scatter, only if correlation > 0.4)

For a Titanic dataset:
- "Survival rate by passenger class" (bar)
- "Age distribution" (histogram)
- "Survival rate by gender" (bar)

# COMMON MISTAKES TO AVOID

- Using `id` or other identifier columns.
- Aggregating without grouping (e.g., AVG without GROUP BY).
- Forgetting LIMIT on high-cardinality categoricals.
- Returning a histogram with a y_column (it has no meaning).
- Using technical labels like `avg_price_log` — translate to `Average price`.
- Generic explanations like "Shows the data" — be specific about what the chart reveals.

Return ONLY the JSON. Nothing else."""
```

### 1.2 User prompt builder

```python
def build_planner_prompt(profile: dict, quality_context: str) -> str:
    """Build the user message for the Chart Planner agent."""
    import json

    # Build a compact per-column summary
    col_summary = []
    for name, info in profile["columns"].items():
        entry = {
            "name": name,
            "semantic_type": info["semantic_type"],
            "missing_pct": info["missing_pct"],
            "unique_count": info["unique_count"],
        }
        if info.get("numeric_summary"):
            ns = info["numeric_summary"]
            entry["stats"] = {
                "min": ns["min"], "max": ns["max"],
                "mean": ns["mean"], "median": ns["median"],
                "std": ns["std"],
                "skewness": ns["skewness"],
                "outlier_count_iqr": ns["outlier_count_iqr"],
            }
        if info.get("sample_values"):
            entry["sample_values"] = info["sample_values"][:5]
        if info.get("warning"):
            entry["warning"] = info["warning"]
        col_summary.append(entry)

    warnings_text = ""
    if profile.get("warnings"):
        warnings_text = (
            f"\n\nDataset warnings:\n{json.dumps(profile['warnings'], indent=2)}"
        )

    return f"""Dataset: {profile.get('filename', 'unknown')}
Rows: {profile['row_count']:,}  |  Columns: {profile['column_count']}
Duplicate rows: {profile.get('duplicate_row_count', 0)}

Column types available:
  numeric:     {profile['semantic_type_summary']['numeric']}
  categorical: {profile['semantic_type_summary']['categorical']}
  datetime:    {profile['semantic_type_summary']['datetime']}
  boolean:     {profile['semantic_type_summary']['boolean']}
  identifier:  {profile['semantic_type_summary']['identifier']}   ← DO NOT USE
  text:        {profile['semantic_type_summary']['text']}   ← DO NOT USE

Column details:
{json.dumps(col_summary, indent=2)}
{warnings_text}

{quality_context}

Generate 3 to 5 useful, varied chart specifications for this dataset.
Return ONLY the JSON object."""
```

### 1.3 Retry prompt builder

```python
def build_planner_retry_prompt(
    original_prompt: str,
    error_message: str,
    available_columns: list[str],
) -> str:
    """Build a retry message after a validation or SQL error."""
    return f"""{original_prompt}

---

YOUR PREVIOUS RESPONSE HAD THIS ERROR:
{error_message}

Available column names in cleaned_data table:
{available_columns}

Please return a corrected JSON object that:
1. Uses ONLY column names from the list above.
2. Fixes the specific error mentioned.
3. Follows ALL the rules from the system prompt.

Return ONLY the corrected JSON object."""
```

---

## 2. Insight Writer Agent — Agent 2

### 2.1 System prompt

```python
INSIGHT_WRITER_SYSTEM = """You are writing short, plain-English insights about a dataset for a non-technical business audience.

# YOUR JOB

You receive a list of charts that were generated, along with the actual query results for each. Write between 3 and 5 short insight sentences that summarize what the data shows.

# RULES

1. **Plain English only.** A consultant or executive should understand without explanation. No statistics jargon (no "outliers", "distribution", "correlation coefficient", "p-value", "standard deviation").

2. **Reference actual numbers.** Every insight must include a specific number, percentage, or comparison from the data. Generic statements like "there are differences between groups" are forbidden.

3. **One or two sentences per insight.** Short and punchy.

4. **3-5 insights total.** Cover different findings, not variations of the same one.

5. **Use comparisons.** "3× more than", "twice as many", "double the rate" land better than raw numbers alone.

6. **Be specific about what the data CAN say** — do not infer causation. "Listings in Manhattan are 3× more expensive than Brooklyn" is fine. "Manhattan listings are expensive because of tourism" is speculation.

7. **No filler.** Skip phrases like "interestingly", "it is worth noting that", "the data shows that". Just say the thing.

# OUTPUT FORMAT

Return ONLY a JSON object. No markdown, no preamble.

{
  "insights": [
    "Insight sentence 1.",
    "Insight sentence 2.",
    "Insight sentence 3."
  ]
}

# EXAMPLES OF GOOD INSIGHTS

For Airbnb:
- "Manhattan listings cost on average $200, almost 3× more than the Bronx ($75)."
- "Brooklyn has the highest number of listings — 20,104 — accounting for 41% of all listings."
- "The number of new listings doubled between 2014 and 2019."

For Titanic:
- "Women survived at a rate of 74%, compared to 19% for men."
- "First-class passengers had a 63% survival rate, more than double third-class (24%)."
- "The average age of survivors (28 years) was slightly younger than non-survivors (31 years)."

# EXAMPLES OF BAD INSIGHTS

- "There is some variation in price across neighborhoods." (no numbers)
- "The mean price exhibits a positively skewed distribution." (jargon)
- "Interestingly, women tend to survive more often." (filler word + vague)
- "This is because Manhattan is a popular tourist destination." (speculation)

Return ONLY the JSON. Nothing else."""
```

### 2.2 User prompt builder

```python
def build_insight_prompt(
    chart_results: list[tuple],
) -> str:
    """
    Build the user message for the Insight Writer agent.

    Args:
        chart_results: list of (ChartSpec, pd.DataFrame) tuples.

    Returns:
        Formatted prompt string with summarized query results.
    """
    import json

    sections = []
    for i, (spec, result_df) in enumerate(chart_results, 1):
        # Compact summary of the result_df: first 10 rows + basic stats
        if result_df.empty:
            data_summary = "No data returned."
        else:
            # Limit rows shown to keep prompt size sane
            preview = result_df.head(10).to_dict(orient="records")
            shape = f"{result_df.shape[0]} rows × {result_df.shape[1]} columns"
            data_summary = (
                f"Result shape: {shape}\n"
                f"First rows:\n{json.dumps(preview, indent=2, default=str)}"
            )

        sections.append(
            f"### Chart {i}: {spec.title}\n"
            f"Business question: {spec.business_question}\n"
            f"Chart type: {spec.chart_type}\n"
            f"Query: {spec.sql_query}\n"
            f"{data_summary}\n"
        )

    charts_block = "\n\n".join(sections)

    return f"""You have {len(chart_results)} chart(s) and their query results below.

{charts_block}

Write 3-5 short, plain-English insights based ONLY on the numbers you see above.
Each insight must reference specific numbers from the data.
Return ONLY the JSON object with the "insights" key."""
```

---

## 3. Key design decisions for prompts

### 3.1 Why JSON-only output

Forcing JSON eliminates parsing ambiguity. The retry loop relies on Pydantic
validation; loose text would break the loop.

### 3.2 Why explicit "DO NOT USE" for identifier/text

LLMs are creative. Without an explicit list of forbidden columns, they will
sometimes choose `passenger_id` for a bar chart "for diversity." Telling them
upfront prevents the retry.

### 3.3 Why include sample values

The semantic type is computed automatically and is sometimes wrong (e.g., a
numeric ID column might be classified as numeric not identifier). Sample values
let the LLM correct for this implicitly: seeing `[1, 2, 3, 4, 5]` for a column
called `id` tells it everything.

### 3.4 Why the Insight Writer is a separate agent

If we put insight generation in the same prompt as chart spec generation:
- The first prompt becomes too long.
- The LLM has not yet seen the actual numbers (only the profile).
- Failure of one task corrupts the other.

Separating them costs one extra LLM call (~$0.0003 at Haiku rates) but improves
quality dramatically. Each agent has one focused job.

### 3.5 Why we send result_df to the Insight Writer

The Insight Writer's value depends on seeing real numbers. Without the actual
query results, it can only restate the chart titles in different words. With
results, it can say "Manhattan averages $200" — which is the entire point.

### 3.6 Token budget per prompt

| Prompt | Approx. tokens | Reasoning |
|---|---|---|
| CHART_PLANNER_SYSTEM | ~700 | Comprehensive rules + examples |
| build_planner_prompt | ~500-1000 | Depends on column count |
| INSIGHT_WRITER_SYSTEM | ~500 | Shorter, more focused |
| build_insight_prompt | ~500-1500 | Depends on number of charts and result sizes |

Total per analysis: ~2,500-4,000 input tokens, ~500-1,000 output tokens.
With Haiku at $1/M input + $5/M output: ~$0.008 per CSV.

---

## 4. Fallback behavior when prompts produce nothing valid

| Agent | Fallback |
|---|---|
| Chart Planner produces 0 valid specs | Use `charts.engine.generate_charts` (deterministic) |
| Chart Planner produces 1-2 specs | Use partial results + fill rest from `charts.engine` |
| Insight Writer fails entirely | Show charts without insight bullets; UI omits the section gracefully |
| Insight Writer produces 1-2 insights | Use what was produced; UI shows them as-is |

The system never blocks on agent failure. The dashboard always renders.

---

**End of Prompt Templates. Version 1.0. Date: 2026-05-19.**
