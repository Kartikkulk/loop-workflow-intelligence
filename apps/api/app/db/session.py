"""Async engine, session factory and the FastAPI session dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

#: How long a writer waits for another writer to finish before giving up.
#:
#: Generous because the thing it waits on is a detection pass, which holds its
#: transaction open across an LLM scoring call per cluster — tens of seconds
#: each on a local model. The default is to fail instantly, and that lost a
#: real write: an approved automation was pushed to n8n, n8n created it, and
#: writing the returned workflow id back raised "database is locked". The
#: workflow existed in n8n while LOOP still believed it had never been
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

if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _apply_sqlite_pragmas(dbapi_connection, _record) -> None:
        """Put SQLite into WAL, on every connection.

        The default rollback journal takes a lock that blocks *readers* for the
        whole of a write transaction, so while detection scored its clusters the
        console could not load a page. WAL lets readers carry on against the
        last committed state while one writer works, which is exactly the shape
        of this application: one long write, many short reads.

        Set per connection because it is a connection-level pragma; the journal
        mode itself is persisted in the database file.
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

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a transactional session."""
    async with SessionLocal() as session:
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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_backfill_added_columns)


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
