# Manual Test Results

**Date:** 2026-05-20
**Tester:** Mahgol Naeh
**Commit:** e42c55f (post BUG 1-4 fixes)
**Environment:** Local, uv run streamlit, real OpenRouter API (claude-haiku-4-5)

---

## Test 1: Titanic CSV

**Dataset:** titanic.csv -- 891 rows, mixed types, missing values

| Metric | Result |
|---|---|
| Total time (upload to dashboard) | ~12 seconds |
| Charts produced | 5 (all LLM-generated) |
| Fallback charts used | 0 |
| Status steps visible | Yes -- all 7 steps appeared in sequence |
| "Upload a different file" button | Visible after results |
| Transparency report | 3 changes flagged |
| Errors or warnings | None |

**Status steps observed:**
1. Loading CSV...
2. Checking data quality...
3. Profiling columns...
4. Asking AI to design charts...
5. Generating 5 charts...
6. Writing insights...
7. Done!

**Transparency report (3 changes):**
- Age column: missing values detected
- Fare column: outliers detected
- Cabin column: dropped (too many nulls)

**Sample insight:**
> "First-class passengers survived at 63% vs 24% for third-class."

**Verdict:** PASS. Within the <15s success criterion. All 5 charts LLM-generated. Insights answer consultant-level business questions.

---

## Test 2: NYC Airbnb 2019 CSV

**Dataset:** AB_NYC_2019.csv -- 48,895 rows, 16 columns, dates and geographic data

| Metric | Result |
|---|---|
| Total time (upload to dashboard) | ~25 seconds |
| Charts produced | 5 (all LLM-generated) |
| Fallback charts used | 0 |
| Status steps visible | Yes -- all steps appeared |
| "Upload a different file" button | Visible after results |
| Transparency report | 8 changes flagged |
| Errors or warnings | None |

**Sample insight:**
> "Manhattan median $150 vs Bronx $65, more than double."

**Verdict:** PASS. Within the <30s success criterion. 48k rows handled without error. Transparency report correctly surfaced 8 data quality changes.

---

## BUG 4 Test: Switching between files

Clicked "Upload a different file" after Titanic results -- widget cleared, session state reset, upload area returned. Uploaded Airbnb CSV -- new pipeline run started with fresh status messages.

**Verdict:** PASS.

---

## UX Bugs Verified Fixed

| Bug | Status |
|---|---|
| BUG 1: No loading indicator | Fixed -- 7-step st.status() visible throughout |
| BUG 2: Subtitle overlap with axis labels | Fixed -- explanations shown as st.caption() below each chart |
| BUG 3: Markdown code formatting in insights | Fixed -- no backtick or dollar-sign artifacts observed |
| BUG 4: No clear way to switch files | Fixed -- "Upload a different file" button clears and resets |

---

## Success Criteria Check

| Criterion | Status |
|---|---|
| Titanic: dashboard in <15s with >=3 charts and >=3 insights | PASS (12s, 5 charts) |
| Airbnb: dashboard in <30s with >=3 charts and >=3 insights | PASS (25s, 5 charts) |
| Fallback works when LLM unavailable | Not tested in this session (tested via unit tests) |
| Transparency report appears for CSVs with quality issues | PASS (3 and 8 changes) |
| Non-technical user can read insights without explanation | PASS (plain sentences, no jargon) |
| uv run pytest passes | PASS (31/31) |
| docker build succeeds | PASS (Phase 9) |
