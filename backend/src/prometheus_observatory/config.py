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
    import_batch_size: int = Field(default=500, ge=10, le=10_000)
    analysis_page_size: int = Field(default=500, ge=10, le=10_000)
    allow_sqlite_create_all: bool = True
    allow_remote_model_calls: bool = False
    local_embedding_base_url: str | None = None
    local_embedding_model: str = "intfloat/multilingual-e5-small"
    local_embedding_revision: str = "unversioned"
    local_linguistic_base_url: str | None = None
    local_linguistic_model: str = "operator-configured-russian-parser"
    local_linguistic_revision: str = "unversioned"
    linguistic_analysis_batch_size: int = Field(default=250, ge=10, le=2_000)
    local_nli_base_url: str | None = None
    local_nli_model: str = "operator-configured-multilingual-nli"
    local_nli_revision: str = "unversioned"
    conversation_graph_candidate_limit: int = Field(default=40, ge=1, le=200)
    conversation_graph_result_limit: int = Field(default=5, ge=1, le=40)
    conversation_graph_batch_size: int = Field(default=250, ge=10, le=2_000)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
