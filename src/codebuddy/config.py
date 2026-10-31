"""Runtime settings. Model IDs come from the environment only; nothing is hard-coded."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CODEBUDDY_", extra="ignore")

    # OpenAI model tiers (required for live use; tests inject fakes)
    model_fast: str | None = None
    model_standard: str | None = None
    model_heavy: str | None = None
    embed_model: str = "text-embedding-3-small"

    # Versions folded into cache keys so stale answers invalidate automatically
    index_version: str = "v1"
    prompt_version: str = "p4"

    # Hint ladder escalation (spec 8.4)
    ladder_max_turns: int = 3
    ladder_max_seconds: int = 600

    # Output token caps per reply mode: a backstop for the word limits in the prompts
    max_tokens_hint: int = 250
    max_tokens_explain: int = 320
    max_tokens_reveal: int = 900
    max_tokens_redirect: int = 90

    # Vector store: embedded path for dev, URL for a server
    qdrant_path: str = "data/index"
    qdrant_url: str | None = None

    # Retrieval
    retrieve_k: int = 30
    rerank_top: int = 5
    relevance_threshold: float = 0.15
    refine_timeout_s: float = 0.3  # budget for the second (classifier query) retrieval
    use_cross_encoder: bool = False  # needs: uv sync --extra rerank

    # Speech-to-text (Groq Whisper, optional OpenAI fallback)
    stt_model: str = "whisper-large-v3-turbo"
    stt_fallback_model: str | None = None  # e.g. an OpenAI transcription model; off when unset
    stt_language: str = "en"
    stt_max_bytes: int = 10_000_000

    # Tools, sandbox, checkpoints
    tools_enabled: bool = True  # False: no tool use at all, so learner code is never run
    mcp_enabled: bool = True  # run tools through an MCP stdio server; False calls them in-process
    sandbox_timeout_s: float = 3.0
    sandbox_memory_mb: int = 256
    sandbox_backend: str = "local"  # see docs/tools-and-approvals.md (Stronger isolation)
    checkpoint_path: str = "data/checkpoints.sqlite"

    # Long-term learner memory (mem0); off by default
    memory_enabled: bool = False
    memory_path: str = "data/memory"
    memory_embedding_dims: int = 1536
    memory_recall_limit: int = 5
    memory_recall_timeout_s: float = 0.6
    memory_write_every: int = Field(4, ge=1)
    memory_secret: SecretStr = SecretStr("")  # signs learner tokens; empty: random per process

    # API hardening
    api_keys: str = ""  # comma-separated; empty disables authentication
    rate_limit_per_minute: int = 30  # per client; 0 disables
    cors_origins: str = ""  # comma-separated origins; empty disables CORS

    # Optional cache and monitoring features (off by default; tune with real data first)
    semantic_cache_threshold: float = 0.0  # cosine similarity needed for an L2 hit; 0 = off
    semantic_cache_max: int = 500
    judge_sample_rate: float = 0.0  # share of hint replies re-checked by an LLM judge

    # Cache TTLs in seconds
    ttl_answer: int = 60 * 60 * 24
    ttl_embedding: int = 60 * 60 * 24 * 30
    ttl_retrieval: int = 60 * 60 * 3
    ttl_session: int = 60 * 60 * 2
    ttl_lock: int = 30

    def require_models(self) -> tuple[str, str, str]:
        missing = [
            name
            for name, value in (
                ("CODEBUDDY_MODEL_FAST", self.model_fast),
                ("CODEBUDDY_MODEL_STANDARD", self.model_standard),
                ("CODEBUDDY_MODEL_HEAVY", self.model_heavy),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Set model IDs in the environment: {', '.join(missing)}")
        assert self.model_fast and self.model_standard and self.model_heavy
        return self.model_fast, self.model_standard, self.model_heavy


@lru_cache
def get_settings() -> Settings:
    return Settings()
