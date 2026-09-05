"""Application configuration.

Every external capability is selected by name here.  Nothing in the codebase
imports a vendor SDK directly outside of ``app/providers``; swapping a provider
is a config change, never a code change.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # ---- app ----
    app_name: str = "Lumen Research Workspace"
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    data_dir: Path = Path("./var")
    database_url: str = ""

    # ---- provider selection (comma separated = ordered fallback chain) ----
    llm_provider: str = "auto"            # auto | anthropic | openai | extractive
    web_search_providers: str = "auto"    # auto | tavily,brave,serper,searxng | none
    academic_providers: str = "openalex,crossref,arxiv,europepmc"
    extractor_provider: str = "http"
    video_provider: str = "youtube"
    vision_provider: str = "auto"
    index_provider: str = "sqlite_fts"
    storage_provider: str = "local"

    # ---- credentials (all optional; absence disables that provider cleanly) ----
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    anthropic_fast_model: str = "claude-haiku-4-5-20251001"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    tavily_api_key: str = ""
    brave_api_key: str = ""
    serper_api_key: str = ""
    searxng_base_url: str = ""
    semanticscholar_api_key: str = ""
    ncbi_api_key: str = ""

    # ---- research policy ----
    contact_email: str = "research-workspace@example.org"   # sent to polite-pool APIs
    user_agent: str = "LumenResearchWorkspace/0.1 (+https://example.org)"
    respect_robots_txt: bool = True
    http_timeout_seconds: float = 25.0
    max_fetch_bytes: int = 8_000_000
    max_upload_bytes: int = 64_000_000
    default_max_sources: int = 12
    max_max_sources: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'workspace.db').resolve()}"

    @property
    def uploads_dir(self) -> Path:
        p = self.data_dir / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def artifacts_dir(self) -> Path:
        p = self.data_dir / "artifacts"
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
