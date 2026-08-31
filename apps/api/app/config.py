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
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5"
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

    # Seed
    seed: int = 42
    seed_days: int = 90

    @property
    def has_llm(self) -> bool:
        """True when a real Anthropic key is configured.

        When false every LLM-backed service falls back to a deterministic
        heuristic, so the product remains fully demonstrable offline.
        """
        return bool(self.anthropic_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
