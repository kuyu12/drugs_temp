from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LLM Ticket Triage"
    database_url: str = "postgresql://triage:triage@localhost:5432/ticket_triage"
    mlflow_tracking_uri: str = "file:./mlruns"
    mlflow_experiment_name: str = "llm-ticket-triage"

    model_name: str = "gpt-4o-mini"
    input_token_cost: float = 0.00000015
    output_token_cost: float = 0.00000060

    prompt_dir: Path = Path("app/prompts")
    eval_dataset_path: Path = Path("app/evals/eval_tickets.json")


@lru_cache
def get_settings() -> Settings:
    return Settings()
