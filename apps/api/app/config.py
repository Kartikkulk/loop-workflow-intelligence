"""Application settings, loaded from the environment / .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo root is wherever the shared .env lives. Searched rather than
# reached by a fixed depth, because the container flattens the tree to
# /app/app and a hardcoded parents[3] raises IndexError there.
_APP_DIR = Path(__file__).resolve().parent
_REPO_ROOT = next(
    (parent for parent in _APP_DIR.parents if (parent / ".env").is_file()),
    _APP_DIR.parent,
)


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
    #: The desktop connector is the only one that can change this machine, so it
    #: describes what it would do until this is explicitly turned off.
    desktop_dry_run: bool = True
    #: Repositories the git connector may read, comma-separated. Empty means
    #: none: an allow-list that defaults to "anything" is not an allow-list.
    git_repos: str = ""

    #: Everything the files connector may touch lives under this one root.
    #: A path that escapes it is refused rather than clamped, because a flow
    #: definition is partly model-generated and "clamp it back inside" quietly
    #: turns a wrong path into a plausible-looking right one.
    files_root: str = "~/LOOP-Invoices"
    #: Describe the move rather than perform it.
    files_dry_run: bool = True

    #: Where automations get pushed to run. The API key is created inside n8n
    #: (Settings > n8n API) and is separate from anything else here, so pushing
    #: a workflow never borrows a credential granted for reading data.
    n8n_base_url: str = "http://localhost:5678"
    #: Where `files_root` is mounted inside the n8n container, per
    #: docker-compose.yml. An exported workflow runs in that container, so a
    #: host path in a file node resolves to nothing there — the translator has
    #: to rewrite paths across the boundary.
    n8n_files_mount: str = "/data/invoices"
    n8n_api_key: str = ""

    #: Same brake for Jira: describe the issue rather than file it.
    jira_dry_run: bool = True
    #: Writing to Jira uses its own credential, deliberately separate from the
    #: OAuth connection under Sources. That connection is an observation tool
    #: and every scope it asks for is read-only; quietly adding write access to
    #: it would buy one workflow at the cost of the promise made to every user
    #: who connects an account. An API token is opt-in, obvious, and revocable
    #: on its own. Create one at:
    #: https://id.atlassian.com/manage-profile/security/api-tokens
    jira_site_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    #: Comma-separated Jira project keys this may file into. Empty means none of
    #: the write paths that need a project will run, which is the safe default
    #: for a flow whose project key came partly from a model.
    jira_allowed_projects: str = ""

    @property
    def jira_allowed_projects_list(self) -> list[str]:
        """`jira_allowed_projects`, upper-cased and split."""
        return [
            part.strip().upper()
            for part in self.jira_allowed_projects.split(",")
            if part.strip()
        ]

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
