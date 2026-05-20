# CSV Dashboard

> Turn any CSV into an insights dashboard for non-technical users.

![Status](https://img.shields.io/badge/status-in%20development-yellow)

Upload a CSV file and get interactive charts plus plain-English insights in seconds.
The system profiles the data, asks an LLM to plan the most relevant charts, executes
the queries via DuckDB, and writes business-readable summaries — all without the user
touching a line of code or a statistical term. A deterministic fallback engine ensures
the dashboard always renders even when the LLM is unavailable.

---

## Setup

_See T-090 for the full setup guide. Placeholder._

```bash
uv sync
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env
```

## Run

```bash
uv run streamlit run src/csv_dashboard/ui/app.py
```

## Test

```bash
uv run pytest
```

## Docker

_See T-080 for the Docker guide. Placeholder._

```bash
docker build -t csv-dashboard -f docker/Dockerfile .
docker run -p 8501:8501 --env-file .env csv-dashboard
```

## Architecture

_See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Placeholder._

9-step pipeline: CSV upload → DuckDB ingestion → data quality → profiling →
Chart Planner agent → SQL execution → Insight Writer agent → Plotly rendering →
Streamlit UI.

## License

MIT
