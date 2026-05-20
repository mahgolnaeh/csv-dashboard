FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

COPY src ./src

EXPOSE 8501
CMD ["uv", "run", "streamlit", "run", "src/csv_dashboard/ui/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
