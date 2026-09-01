"""Application settings, loaded from the environment / .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Every tunable in LOOP. See .env.example for documentation of each."""

    model_config = SettingsConfigDict(
        env_prefix="LOOP_",
        env_file=(_REPO_ROOT / ".env", ".env"),
        extra="ignore",
    )

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = "qwen2.5:7b-instruct"
    ollama_base_url: str = "http://localhost:11434"
    ollama_vision_model: str = ""
    llm_cache: bool = True
    llm_max_retries: int = 3

    # Database
    database_url: str = "sqlite+aiosqlite:///./loop.db"

    # Detection (F2)
    session_gap_minutes: int = 15
    cluster_threshold: float = 0.35
    sequence_weight: float = 0.45
    set_weight: float = 0.30
    org_user_threshold: int = 3

    # Scoring (F3)
    interruption_cost_minutes: float = 4.0
    context_switch_window_minutes: int = 10
    do_not_automate_threshold: float = 0.4
    working_weeks: int = 48

    # Trust ladder (F7)
    shadow_window: int = 5
    shadow_promotion_threshold: float = 0.90
    shadow_min_runs: int = 5
    demotion_lookback: int = 3

    # Execution (F5)
    enable_mock_connectors: bool = True

    # Self-healing (F8)
    patch_auto_apply_confidence: float = 0.9
    exception_rule_min_samples: int = 3

    # Where the two halves of LOOP live. Used to build the OAuth redirect URI
    # and to send the browser back to the console after a provider callback.
    api_base_url: str = "http://localhost:8000"
    console_url: str = "http://localhost:3000"

    # Personal OAuth app registrations. Empty by default and expected to stay
    # that way: the normal path is to type them into the Sources page, which
    # stores them in the local database. These exist for anyone who would
    # rather keep them in a .env file.
    google_client_id: str = ""
    google_client_secret: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    atlassian_client_id: str = ""
    atlassian_client_secret: str = ""
    slack_client_id: str = ""
    slack_client_secret: str = ""

    # Seed
    seed: int = 42
    seed_days: int = 90

    @property
    def has_llm(self) -> bool:
        """True when an LLM provider is configured.

        The default provider is local Ollama. If Ollama is not running, every
        text LLM feature still falls back to deterministic heuristics.
        """
        return self.llm_provider.strip().lower() == "ollama" and bool(self.llm_model.strip())

    @property
    def has_vision_llm(self) -> bool:
        """True when a local vision-capable Ollama model is configured."""
        return self.llm_provider.strip().lower() == "ollama" and bool(
            self.ollama_vision_model.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
