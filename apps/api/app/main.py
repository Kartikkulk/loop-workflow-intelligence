"""LOOP API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import (
    automations,
    clusters,
    connect,
    demo,
    governance,
    ingest,
    sources,
)
from app.config import settings
from app.db.session import SessionLocal, engine, init_db
from app.llm.client import llm
from app.schemas.common import Health, LlmUsage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-18s %(message)s",
)
logger = logging.getLogger("loop")

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup and seed the registries if the DB is empty."""
    await init_db()
    async with SessionLocal() as session:
        from app.services.demo_state import seed_registries

        await seed_registries(session)
        await session.commit()

        # Credentials the person typed into the Sources page in an earlier run.
        await connect.reload_credentials(session)
    logger.info(
        "LOOP api ready — db=%s llm=%s connectors=%s",
        settings.database_url.split("://")[0],
        settings.llm_description
        if llm.available
        else "deterministic fallback",
        "mock" if settings.enable_mock_connectors else "live",
    )
    yield
    await engine.dispose()


app = FastAPI(
    title="LOOP — Workflow Intelligence Platform",
    description=(
        "Detects repetitive enterprise workflows from activity logs, converts them into "
        "automations, and promotes those automations from suggested to autonomous through a "
        "measured trust ladder."
    ),
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # The console is a separate origin in development and in most deployments;
    # SSE needs this to work. Built from configuration rather than hard-coded,
    # because a deployed console lives at neither localhost address.
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

v1 = APIRouter(prefix="/api/v1")
v1.include_router(ingest.router)
v1.include_router(clusters.router)
v1.include_router(automations.router)
v1.include_router(sources.router)
v1.include_router(connect.router)
v1.include_router(governance.router)
v1.include_router(demo.router)
app.include_router(v1)


@app.get("/health", response_model=Health, tags=["meta"])
async def health() -> Health:
    """Liveness plus the three facts that determine how the system behaves."""
    database = "unknown"
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # noqa: BLE001
        database = f"error: {exc}"

    return Health(
        status="ok" if database == "ok" else "degraded",
        database=database,
        llm=(
            settings.llm_description
            if llm.available
            else "deterministic fallback (no local model)"
        ),
        connectors="mock" if settings.enable_mock_connectors else "live",
        version=VERSION,
    )


@app.get("/api/v1/llm-usage", response_model=LlmUsage, tags=["meta"])
async def llm_usage() -> LlmUsage:
    """Running LLM usage. Local Ollama models report zero hosted spend."""
    return LlmUsage(
        available=llm.available,
        model=settings.llm_description if llm.available else "none",
        calls=llm.call_count,
        fallbacks=llm.fallback_count,
        input_tokens=llm.total_input_tokens,
        output_tokens=llm.total_output_tokens,
        estimated_cost_usd=round(llm.estimated_cost_usd, 4),
    )
