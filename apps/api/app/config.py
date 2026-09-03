"""Application settings, loaded from the environment / .env file."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo root is wherever the shared .env lives. Searched rather than
# reached by a fixed depth, because the container flattens the tree to
# /app/app and a hardcoded parents[3] raises IndexError there.
_APP_DIR = Path(__file__).resolve().parent
_REPO_ROOT = next(
    (parent for parent in _APP_DIR.parents if (parent / ".env").is_file()),
    _APP_DIR.parent,
)

#: libpq understands these; asyncpg raises TypeError on them. `sslmode` has a
#: direct equivalent, so it is translated; `channel_binding` has none, and is
#: dropped rather than passed through to become a crash on startup.
_LIBPQ_ONLY = {"sslmode": "ssl", "channel_binding": None}


def normalise_database_url(url: str) -> str:
    """Make a hosted provider's connection string usable by the async engine.

    Neon, Supabase, Render and Heroku all hand out a libpq URL — `postgresql://`
    with `?sslmode=require` — and every part of that is wrong here. The engine is
    async, so it needs an explicit driver; asyncpg then rejects libpq's own
    parameter names. Someone told to copy a URL from a dashboard should not have
    to know that, so the rewrite happens here instead of in a README instruction.

    A URL that already names a driver is returned untouched.
    """
    scheme, netloc, path, query, fragment = urlsplit(url)
    if scheme not in ("postgres", "postgresql"):
        return url

    params = [
        (_LIBPQ_ONLY.get(key, key), value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if _LIBPQ_ONLY.get(key, key) is not None
    ]

    # A PgBouncer pooler in transaction mode hands out a different backend per
    # statement, so asyncpg's prepared-statement cache describes a session that
    # is no longer there. Neon's pooled endpoint is the common case of this.
    if "-pooler" in netloc and not any(k == "prepared_statement_cache_size" for k, _ in params):
        params.append(("prepared_statement_cache_size", "0"))

    return urlunsplit(("postgresql+asyncpg", netloc, path, urlencode(params), fragment))


class Settings(BaseSettings):
    """Every tunable in LOOP. See .env.example for documentation of each."""

    model_config = SettingsConfigDict(
        env_prefix="LOOP_",
        env_file=(_REPO_ROOT / ".env", ".env"),
        extra="ignore",
    )

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:8b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_vision_model: str = ""
    llm_cache: bool = True
    llm_max_retries: int = 3

    # OpenAI, used only when Ollama cannot answer. Leave the key empty and
    # nothing changes: calls that fail locally go on to the deterministic
    # fallback exactly as before. Setting it buys a second chance before that,
    # which matters when the local model is small enough to produce output that
    # parses but is not usable.
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    # Database
    database_url: str = "sqlite+aiosqlite:///./loop.db"

    @field_validator("database_url")
    @classmethod
    def _accept_a_provider_url(cls, value: str) -> str:
        return normalise_database_url(value)

    # Detection (F2)
    session_gap_minutes: int = 15
    cluster_threshold: float = 0.35
    sequence_weight: float = 0.45
    set_weight: float = 0.30
    org_user_threshold: int = 3

    #: How many times a pattern must be seen before it counts as an opportunity.
    #: The default is about statistical support, not tidiness: annual hours are
    #: projected from an observed weekly frequency, and a dozen observations
    #: spread over a quarter give an estimate too noisy to put a number on.
    #: Lower it when watching a live collector, where the point is to see
    #: detection work at all rather than to project a year from it.
    #:
    #: In demo mode this floor is not used directly — `effective_min_instances`
    #: drops it to `discovery_min_occurrences` so a task performed two or three
    #: times can surface as an early candidate.
    min_instances: int = 15
    #: A two-step signature is usually a truncation artefact — a longer workflow
    #: cut in half because an unrelated event landed in the middle of it.
    min_signature_steps: int = 3

    # ── low-occurrence discovery (demo) ──────────────────────────────────
    #: "production" keeps the full statistical floor (min_instances). "demo"
    #: lowers the floor so a task repeated two or three times is detectable,
    #: which is what a live pitch can actually produce by hand. Demo mode
    #: lowers *discovery* thresholds only — every safety gate (guards, connector
    #: validation, dependency checks, dry-run, approval) is untouched.
    discovery_mode: str = "demo"
    #: Fewest repeats that can produce a candidate at all, in demo mode.
    discovery_min_occurrences: int = 2
    #: At or above this many repeats a demo candidate is "strong". Set to 5 so a
    #: task has to be performed a handful of times — enough to be convincing on
    #: stage — before it is presented as a proven pattern rather than an early one.
    discovery_strong_occurrences: int = 5
    #: A two-occurrence candidate needs at least this run-to-run similarity, so
    #: two unrelated tasks that happen to be short are not called repetitive.
    discovery_min_similarity: float = 0.70
    #: Similarity at or above which a candidate is treated as strong evidence.
    discovery_strong_similarity: float = 0.85
    #: The weighted confidence a low-occurrence candidate must clear to show.
    discovery_min_confidence: float = 0.60
    #: Confidence at or above which a candidate is treated as strong evidence.
    discovery_strong_confidence: float = 0.75

    @property
    def demo_mode(self) -> bool:
        return self.discovery_mode.strip().lower() == "demo"

    @property
    def effective_min_instances(self) -> int:
        """The instance floor detection actually applies.

        Production uses the full statistical floor. Demo drops it to the
        low-occurrence minimum so a hand-performed pattern is detectable — the
        weaker evidence is then labelled `early`/`moderate` rather than hidden.
        """
        if self.demo_mode:
            return max(1, self.discovery_min_occurrences)
        return self.min_instances

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
    #: The same n8n, as a person's browser can reach it. Inside Docker the two
    #: differ: the API talks to `http://n8n:5678` over the compose network,
    #: which resolves nowhere in a browser, so a link built from `n8n_base_url`
    #: lands on DNS_PROBE_FINISHED_NXDOMAIN. Empty means the two are the same,
    #: which is true whenever LOOP is not containerised.
    n8n_public_url: str = ""
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
    #: Extra browser origins allowed to call this API, comma-separated.
    #:
    #: `console_url` is always allowed, so a normal deployment sets that alone.
    #: This exists for the cases where the console is reachable at more than one
    #: address — a Cloud Run revision URL alongside a custom domain, say — and
    #: an origin missing from the list fails as a CORS error in the browser
    #: with a working API behind it, which is a miserable thing to debug.
    extra_cors_origins: str = ""

    # ── sign-in (demo deployment) ────────────────────────────────────────
    #: Shared password for the named demo users. One password for everyone is
    #: a deliberate demo trade-off, not an oversight — see app/auth.py.
    demo_password: str = "Loop@123"
    #: Signs the session cookie. Change it and every existing cookie stops
    #: verifying, which is how you sign everybody out.
    session_secret: str = "loop-demo-session-secret-change-me"
    #: Where each user's database file lives. One file per person.
    data_dir: str = "./data"
    #: With sign-in off, everything shares one database and no login is asked
    #: for — which is what local development and the test suite want.
    require_login: bool = False

    @property
    def cors_origins(self) -> list[str]:
        """Every browser origin permitted to call this API."""
        origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            self.console_url.strip().rstrip("/"),
        ]
        origins += [o.strip().rstrip("/") for o in self.extra_cors_origins.split(",")]
        return sorted({o for o in origins if o})

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

        The default provider is local Ollama, with OpenAI as a second chance if
        a key is set. If neither can answer, every LLM feature still falls back
        to deterministic heuristics, so this being False is never fatal.
        """
        if self.has_openai_fallback:
            return True
        return self.llm_provider.strip().lower() == "ollama" and bool(self.llm_model.strip())

    @property
    def has_openai_fallback(self) -> bool:
        """True when an OpenAI key is configured to catch local failures."""
        return bool(self.openai_api_key.strip()) and bool(self.openai_model.strip())

    @property
    def llm_description(self) -> str:
        """What the health endpoint reports, including the standby provider."""
        primary = f"{self.llm_provider}:{self.llm_model}"
        if self.has_openai_fallback:
            return f"{primary} (fallback openai:{self.openai_model})"
        return primary

    @property
    def has_vision_llm(self) -> bool:
        """True when a local vision-capable Ollama model is configured."""
        return self.llm_provider.strip().lower() == "ollama" and bool(
            self.ollama_vision_model.strip()
        )

    @property
    def n8n_link_base(self) -> str:
        """The n8n address to put in front of a person, never to call.

        Every URL that ends up in a link or an instruction has to be resolvable
        from the browser, which is a different network from the one the API
        calls n8n on. Use `n8n_base_url` for requests and this for anything a
        person will click.
        """
        return (self.n8n_public_url or self.n8n_base_url).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
