"""Central settings, loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    # Dataset (read-only) and local state
    data_root: Path = PROJECT_ROOT.parent / "phdata-ml-pc-india-7e93e7a8beac"
    storage_dir: Path = PROJECT_ROOT / "storage"

    # Pilot scope: the single incident category this POC handles end-to-end
    pilot_category: str = "Printers"

    # LLM runtime
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b-instruct"
    embed_model: str = "nomic-embed-text"
    llm_temperature: float = 0.0
    llm_num_ctx: int = 8192  # Ollama's default context would silently truncate KB excerpts

    # Retrieval
    retrieval_top_k: int = 6
    chunk_max_words: int = 350

    # Guardrail thresholds
    min_retrieval_score: float = 0.35
    min_triage_confidence: float = 0.6

    @field_validator("data_root", "storage_dir")
    @classmethod
    def _resolve(cls, v: Path) -> Path:
        # relative paths in .env are relative to the project, not the launch directory
        return (v if v.is_absolute() else PROJECT_ROOT / v).resolve()

    @property
    def chroma_dir(self) -> Path:
        return self.storage_dir / "chroma"

    @property
    def itsm_db(self) -> Path:
        return self.storage_dir / "itsm.db"

    @property
    def audit_db(self) -> Path:
        return self.storage_dir / "audit.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
