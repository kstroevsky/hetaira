from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROMETHEUS_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "Prometheus Observatory"
    database_url: str = "sqlite:///./backend/data/prometheus.db"
    object_store: Path = Path("./backend/data/objects")
    seed_demo: bool = True
    cors_origins: str = "http://localhost:5173"
    ontology_version: str = "0.1.0"
    pipeline_version: str = "0.1.0"
    default_language: str = "ru"
    default_session_gap_hours: int = Field(default=8, ge=1, le=72)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
