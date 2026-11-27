"""FastAPI application entrypoint for EnclaveRAG."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg import Error as PsycopgError

from app.api.routes import router as api_router
from app.core.config import settings
from app.core.db import check_db_health, close_db_pool, init_db_pool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage PostgreSQL AsyncConnectionPool across application lifespan."""
    try:
        await init_db_pool()
    except (PsycopgError, OSError) as exc:
        logger.warning("Database pool unavailable at startup: %s", exc)
    try:
        yield
    finally:
        await close_db_pool()


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Zero-Trust Multi-Tenant RAG with PostgreSQL RLS & pgvector",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix="/api/v1")

    @application.get("/health", tags=["system"])
    async def health_check() -> dict[str, object]:
        db_status = await check_db_health()
        return {
            "status": "ok" if db_status.get("connected") else "degraded",
            "service": settings.app_name,
            "database": db_status,
        }

    return application


app = create_app()

if __name__ == "__main__":
    loop = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
    uvicorn.run(app, host="127.0.0.1", port=8000, loop=loop)
