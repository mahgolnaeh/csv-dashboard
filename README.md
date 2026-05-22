# CSV Dashboard

> Turn any CSV into an insights dashboard for non-technical users.

![Status](https://img.shields.io/badge/status-complete-green)
![Tests](https://img.shields.io/badge/tests-31%20passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

## What It Does

Upload any CSV file and receive a dashboard with interactive Plotly charts and
plain-English insights -- no code, no statistics knowledge required. The system
loads the data into DuckDB, detects and auto-fixes data quality issues (currency
symbols, sentinel nulls, whitespace), profiles the dataset, asks an LLM to plan
the most relevant charts, executes the queries, and writes business-readable
summaries. A deterministic fallback engine (12 rule-based chart types, R01-R12)
ensures the dashboard always renders even if the LLM is unavailable.

Validated on: Titanic (891 rows, mixed types, missing values) and NYC Airbnb 2019
(48,895 rows, 16 columns, dates and geographic data).

---

## Architecture

```
[1] CSV upload (Streamlit file_uploader)
        |
[2] DuckDB loads CSV              -> table: raw_data
        |
[3] data_quality.py               -> VIEW: cleaned_data  +  quality report
        |
[4] profiler.py                   -> compact profile dict (~1000 tokens)
        |
[5] Agent 1: Chart Planner (LLM)  -> 3-5 chart specs (JSON)
        |
[6] Pydantic + SQL validation     -> blocks bad specs; retry LLM once on error
        |
[7] DuckDB executes each spec SQL on cleaned_data
        |
[8] Agent 2: Insight Writer (LLM) -> plain-English insights from query results
        |
[9] Plotly renders + Streamlit displays charts, insights, transparency report
        |
    (Fallback at any step: chart_engine.py, deterministic R01-R12 rules)
```

For a deeper explanation see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Tech Stack

| Layer | Choice | Purpose |
|---|---|---|
| Language | Python 3.11+ | Core runtime |
| Package manager | uv | Fast installs, reproducible lockfile |
| Data engine | DuckDB | SQL on CSVs, single source of truth |
| Profiling | pandas 2.x | Profile-time DataFrame ops only |
| Validation | Pydantic v2 | Chart spec schema, cross-field rules |
| LLM gateway | OpenRouter via httpx | Model-agnostic, no SDK dependency |
| Default LLM | Claude Haiku 4.5 | Fast, low-cost chart planning |
| Charts | Plotly | Interactive, embedded in Streamlit |
| UI | Streamlit | Fast MVP for non-technical users |
| Logging | structlog | JSON to stdout |
| Testing | pytest + pytest-mock | 31 tests, LLM always mocked |
| Container | Docker | Reproducible, secrets via env-file |

---

## Quick Start

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/), an OpenRouter API key.

```bash
# 1. Clone and install
git clone <repo-url>
cd csv-dashboard
uv sync

# 2. Configure
cp .env.example .env
# Edit .env and set: OPENROUTER_API_KEY=your_key_here

# 3. Run
uv run streamlit run src/csv_dashboard/ui/app.py
```

Open http://localhost:8501 and upload a CSV file.

The default model is `anthropic/claude-haiku-4-5` via OpenRouter. You can override
any setting in `.env` -- see `.env.example` for the full list.

---

## Docker

```bash
# Build (from project root)
docker build -t csv-dashboard -f docker/Dockerfile .

# Run
docker run -p 8501:8501 --env-file .env csv-dashboard
```

Open http://localhost:8501.

The API key is injected at runtime via `--env-file`. It is never baked into the image.

---

## Testing

```bash
uv run pytest
```

31 tests pass in under 5 seconds. All LLM calls are mocked -- no OpenRouter key needed.

```bash
# With coverage report
uv run pytest --cov=src
```

---

## Project Structure

```
csv-dashboard/
├── src/csv_dashboard/
│   ├── config.py                    pydantic-settings, reads .env
│   ├── ingestion/loader.py          DuckDB CSV ingestion -> raw_data
│   ├── quality/data_quality.py      quality checks + cleaned_data VIEW
│   ├── profiling/profiler.py        compact dataset profile for LLM
│   ├── insights/
│   │   ├── llm_client.py            OpenRouter HTTP client (httpx)
│   │   ├── chart_spec.py            Pydantic models + SQL validators
│   │   └── prompts.py               system prompts for both agents
│   ├── agents/
│   │   ├── chart_planner.py         Agent 1: generates chart specs from profile
│   │   └── insight_writer.py        Agent 2: writes plain-English insights
│   ├── charts/
│   │   ├── engine.py                deterministic fallback (R01-R12 rules)
│   │   └── renderer.py              Plotly figure builder
│   ├── transparency/transparency.py plain-English report of every data change
│   ├── orchestrator/pipeline.py     wires all modules; single entry point
│   └── ui/app.py                    Streamlit UI with caching
├── tests/                           31 unit + e2e tests, LLM always mocked
├── docker/Dockerfile
├── .github/workflows/ci.yml
├── docs/
│   ├── ARCHITECTURE.md              deep dive into the pipeline
│   ├── TECHNICAL_DESIGN.md          module internals, data contracts, design decisions
│   ├── TRADE_OFFS.md                what was cut and why
│   └── PRODUCTION_NOTES.md          cost, latency, failure modes, scaling
├── pyproject.toml
└── .env.example
```

---

For deeper reading see [docs/](docs/) — [architecture](docs/ARCHITECTURE.md), [technical design](docs/TECHNICAL_DESIGN.md), trade-offs, and production notes.

---

## Presentation

A slide deck summarizing the project, architecture, and trade-offs:
[CSV_Dashboard_Presentation.pptx](CSV_Dashboard_Presentation.pptx).

---

## License

MIT
