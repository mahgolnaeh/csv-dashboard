# Phase 0 Results

Validated: 2026-05-20. Python 3.12.4, pandas 3.0.3, DuckDB (latest via uv).

---

## Titanic (titanic.csv, 891 rows)

- Elapsed: 1.86 seconds (budget: 15s)
- Charts: 39 (R00, R12, R01x2, R02x4, R03x2, R04x24, R05x2, R06x1, R11x2)
- Quality warnings: 3 (SibSp outliers, Fare outliers, Cabin 77% missing)
- Transparency sentences: 3 — all readable, non-jargon
- Columns dropped: 0
- PassengerId correctly classified as identifier (skipped by chart_engine)
- Survived, Pclass classified as numeric (integer 0/1 and 1/2/3) — expected behavior

## NYC Airbnb (AB_NYC_2019.csv, 48895 rows)

- Elapsed: 5.88 seconds (budget: 30s)
- Charts: 66 (R00, R12, R01x1, R02x7, R03x2, R04x40, R05x1, R06x1, R07x1, R08x8, R11x3)
- Quality warnings: 6 (longitude, price, min_nights, n_reviews, reviews_per_month, host_listings outliers)
- Transparency sentences: 8 — all readable
- Columns dropped: 0
- `last_review` correctly detected as datetime; R07/R08 charts generated
- `id`, `host_id` classified as numeric by profiler (approx_unique < threshold) but
  correctly skipped as identifiers by chart_engine (pattern match `^id$`, `_id$`)
- `name`, `host_name` treated as high-cardinality categorical (R11 + many R04 pairs)

---

## Bugs fixed during Phase 0

### Bug 1: `"ME"` frequency in `to_period()` — pandas 3.x incompatibility
- **File:** `chart_engine.py`, functions `chart_records_over_time` and `chart_avg_over_time`
- **Root cause:** pandas 3.x uses `"ME"` for month-end in `resample()` but `to_period()` still requires `"M"`. Code used `"ME"` everywhere.
- **Fix:** Changed `freq = "ME"` to `freq = "M"` in both functions.

### Bug 2: VARCHAR dtype `str` not matched as categorical — pandas 3.x incompatibility
- **File:** `chart_engine.py`, `_infer_datetime()` and `generate_charts()` column classification
- **Root cause:** pandas 3.x + DuckDB returns VARCHAR columns as `StringDtype` (dtype name `"str"`), not `object`. The check `series.dtype == object` was False for all string columns, silently dropping them from categorical_cols. R03 and R04 charts were never generated.
- **Fix:** Replaced `series.dtype == object` with `pd.api.types.is_string_dtype(series)` in column classification. Same for `_infer_datetime`. Also removed deprecated `infer_datetime_format=True` parameter, replaced with `format="mixed", errors="coerce"` and a `>= 0.8` parse-success threshold.

---

### Bug 3: Combinatorial explosion in R04 and R08
- **File:** `chart_engine.py`, `generate_charts()`
- **Root cause:** R04 generated `n_numeric × n_categorical` charts with no cap. R08 generated `n_datetime × n_numeric`. On Airbnb: R04=40, R08=8 of 66 total — unusable for a non-technical user.
- **Fix:** Priority-ordered generation with `max_charts=6` default. R04 capped at `MAX_R04_PER_CAT=2` numerics (sorted by std) per low-cardinality categorical (≤ MAX_CARDINALITY_BAR=20 unique). R08 capped at `MAX_R08_PER_DT=2` numerics. R05 reduced to single strongest pair. Pool mode (`max_charts=None`) still returns all charts ordered by priority.

## Decisions made based on Phase 0

1. **All three bugs fixed in `_existing_code/chart_engine.py` before Phase 1.** The canonical source is already corrected. Phase 1 (T-010) will copy the fixed file.

2. **39 / 66 fallback charts is expected.** The chart_engine generates all applicable charts by design. In the live pipeline, LLM agents select 3-5 charts; the fallback only triggers when LLM is unavailable. The Streamlit UI shows all fallback charts in a 2-column grid — acceptable for an edge case.

3. **No threshold tuning needed.** All time budgets met with headroom (Titanic 12% used, Airbnb 20% used). No modules need refactoring before Phase 1.

4. **Profiler semantic types are accurate enough.** Minor nuances (`Survived` as numeric rather than boolean) are cosmetic and do not break charts. The LLM agents receive the full profile and can interpret semantic types independently.

---

## Phase 0 exit criteria — all met

- [x] Both datasets run through 5 modules without errors.
- [x] Both datasets meet time budgets.
- [x] Manual inspection shows no obvious problems.
- [x] This file exists with real numbers and observations.

**Safe to proceed to Phase 1 (T-001: Initialize project with uv).**
