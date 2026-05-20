from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str
    chart_planner_model: str = "anthropic/claude-haiku-4.5"
    insight_writer_model: str = "anthropic/claude-haiku-4.5"
    max_llm_retries: int = 1
    llm_max_tokens: int = 2048
    top_n_categories: int = 10
    missing_threshold: float = 0.40
    correlation_threshold: float = 0.40
    heatmap_threshold: float = 0.50


settings = Settings()
