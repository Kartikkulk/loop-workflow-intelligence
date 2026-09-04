"""Async engine, session factory and the FastAPI session dependency."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import HTTPException, Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

logger = logging.getLogger("loop.db")

#: Duplicated from app.auth to avoid importing it at module scope, which would
#: be circular — auth reads settings, settings is imported here.
SESSION_COOKIE_NAME = "loop_session"

_is_sqlite = settings.database_url.startswith("sqlite")

#: How long a writer waits for another writer to finish before giving up.
#:
#: Generous because the thing it waits on is a detection pass, which holds its
#: transaction open across an LLM scoring call per cluster — tens of seconds
#: each on a local model. The default is to fail instantly, and that lost a
#: real write: an approved automation was pushed to n8n, n8n created it, and
#: writing the returned workflow id back raised "database is locked". The
#: workflow existed in n8n while Kriyā AI still believed it had never been
#: approved, so the next click would have created a duplicate.
_BUSY_TIMEOUT_SECONDS = 60

_connect_args = (
    {"check_same_thread": False, "timeout": _BUSY_TIMEOUT_SECONDS} if _is_sqlite else {}
)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args=_connect_args,
)

def _apply_sqlite_pragmas(dbapi_connection, _record) -> None:
    """Put SQLite into WAL, on every connection.

    The default rollback journal takes a lock that blocks *readers* for the
    whole of a write transaction, so while detection scored its clusters the
    console could not load a page. WAL lets readers carry on against the last
    committed state while one writer works, which is exactly the shape of this
    application: one long write, many short reads.

    Named rather than a decorated closure so the per-user engines built below
    can register the same listener.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_SECONDS * 1000}")
        # NORMAL is the documented companion to WAL: durable across process
        # crashes, and only at risk from an OS-level crash mid-write.
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


if _is_sqlite:
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)


SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ── per-user databases ──────────────────────────────────────────────────────
#
# One database file per signed-in person, resolved per request. Every endpoint
# already depends on `get_session`, so isolating there isolates all of them at
# once — there is no query anywhere that can forget to scope itself, because
# scoping is not a filter it applies but the connection it is handed.

_user_engines: dict[str, AsyncEngine] = {}
_user_sessionmakers: dict[str, async_sessionmaker] = {}
_engine_lock = asyncio.Lock()


def _build_engine(url: str) -> AsyncEngine:
    """An engine with this project's SQLite pragmas already applied."""
    built = create_async_engine(
        url,
        echo=False,
        future=True,
        connect_args=(
            {"check_same_thread": False, "timeout": _BUSY_TIMEOUT_SECONDS}
            if url.startswith("sqlite")
            else {}
        ),
    )
    if url.startswith("sqlite"):
        event.listen(built.sync_engine, "connect", _apply_sqlite_pragmas)
    return built


async def _ensure_postgres_database(url: str) -> None:
    """Create this user's database if the server does not have it yet.

    CREATE DATABASE cannot run inside a transaction, so it goes through a
    connection in autocommit. Existence is checked first rather than relying on
    catching the error, because "already exists" and "you may not create
    databases" both arrive as the same exception class and only one of them is
    fine to ignore.
    """
    target = url.rpartition("/")[2].split("?")[0]
    admin_url = settings.database_url
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target}
            )
            if not exists:
                # The name comes from _SAFE_USERNAME, so it cannot contain a
                # quote; parameters are not allowed in DDL.
                await conn.execute(text(f'CREATE DATABASE "{target}"'))
                logger.info("created database %s", target)
    finally:
        await admin.dispose()

async def sessionmaker_for(username: str) -> async_sessionmaker:
    """The session factory for one user, creating their database on first use.

    Guarded by a lock because two simultaneous first requests from the same
    person would otherwise both see no engine and both run `create_all`.
    """
    if username in _user_sessionmakers:
        return _user_sessionmakers[username]

    async with _engine_lock:
        if username in _user_sessionmakers:  # settled while waiting
            return _user_sessionmakers[username]

        from app.auth import database_url_for

        url = database_url_for(username)
        if url.startswith("sqlite"):
            Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        else:
            await _ensure_postgres_database(url)
        built = _build_engine(url)
        async with built.begin() as conn:
            from app import models  # noqa: F401 — registers every table
            from app.db.base import Base

            await conn.run_sync(Base.metadata.create_all)

        _user_engines[username] = built
        _user_sessionmakers[username] = async_sessionmaker(
            bind=built, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )
        return _user_sessionmakers[username]


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a transactional session.

    With sign-in enabled the session is bound to the requesting user's own
    database; with it off — local development and the tests — everything shares
    the one configured database, exactly as before.
    """
    factory = SessionLocal
    if settings.require_login:
        from app.auth import resolve_user

        username = resolve_user(request)
        if not username:
            # Refused, not served from the default database. Falling back to
            # the shared one meant an unauthenticated caller was handed whatever
            # happened to be in it — which on a deployment with sign-in turned
            # on is precisely the data sign-in exists to separate.
            raise HTTPException(401, "Sign in to use Kriyā AI.")
        factory = await sessionmaker_for(username)

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables. Used on startup and by the seed script.

    The hackathon build uses create_all rather than Alembic migrations so a
    clean clone is runnable in one command; the models are written to be
    Alembic-compatible when migrations are introduced.
    """
    from app import models  # noqa: F401  — ensures every model is registered
    from app.db.base import Base

    # Retried, because the database may not be reachable the instant this
    # process starts. On Cloud Run the connection goes through a sidecar proxy
    # that mounts its socket as the container boots: the path exists before
    # anything is listening on it, so the first attempt gets ECONNREFUSED and
    # the container exits before it ever serves a request.
    last: Exception | None = None
    for attempt in range(10):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(_backfill_added_columns)
            return
        except Exception as exc:  # noqa: BLE001 — any connection fault is worth a retry
            last = exc
            logger.warning("database not ready (attempt %d/10): %s", attempt + 1, exc)
            await asyncio.sleep(2)
    raise RuntimeError(f"database never became reachable: {last}")


#: Columns added after the first release. create_all creates missing *tables*
#: but never adds a column to a table that already exists, so a database seeded
#: before these fields existed would raise on the first insert/select. Adding
#: them here is additive and idempotent — it preserves the real activity a
#: database may already hold, which a drop-and-recreate would destroy. Each
#: entry is (table, column, DDL type + default). When Alembic is introduced,
#: this becomes its first migration and this helper goes away.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("clusters", "evidence_level", "VARCHAR(16) NOT NULL DEFAULT 'strong'"),
    ("clusters", "requires_more_observation", "BOOLEAN NOT NULL DEFAULT 0"),
    ("clusters", "dismissed", "BOOLEAN NOT NULL DEFAULT 0"),
    ("automations", "approved", "BOOLEAN NOT NULL DEFAULT 0"),
)


def _backfill_added_columns(connection) -> None:
    """Add any post-release column that an older database is missing."""
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    for table, column, ddl in _ADDED_COLUMNS:
        if table not in existing_tables:
            continue  # create_all just made it, with the column already present
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in columns:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def drop_db() -> None:
    """Drop all tables. Backs POST /api/v1/demo/reset."""
    from app import models  # noqa: F401
    from app.db.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
