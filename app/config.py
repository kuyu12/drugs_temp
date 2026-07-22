from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Drug Registry Service"
    drug_registry_base_url: str = "https://israeldrugs.health.gov.il"
    drug_registry_timeout_seconds: float = 20.0
    drug_registry_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    min_request_delay_seconds: float = 1.5
    max_request_delay_seconds: float = 4.0
    retry_attempts: int = 4
    retry_backoff_seconds: float = 3.0
    block_cooldown_seconds: float = 30.0
    cache_dir: str = ".cache/drug_registry"
    cache_ttl_hours: int = 168
    price_dictionary_csv_path: Path = Path("data_sources/drug_price_dictionary.csv")
    drug_aliases_csv_path: Path = Path("data_sources/drug_aliases.csv")


@lru_cache
def get_settings() -> Settings:
    return Settings()
