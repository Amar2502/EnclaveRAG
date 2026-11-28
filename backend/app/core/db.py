"""PostgreSQL async pool and transaction-scoped RLS binding."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings


@dataclass(frozen=True)
class RLSContext:
    """Verified tenant and clearance claims bound to a single transaction."""

    org_id: UUID
    user_id: UUID
    clearance_level: int
    department: str = "General"
    is_org_admin: bool = False
    token_version: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.clearance_level <= 4:
            raise ValueError("clearance_level must be between 1 and 4")


_pool: AsyncConnectionPool | None = None


async def _configure_connection(conn: AsyncConnection) -> None:
    """Register pgvector codecs on each pooled connection."""
    await register_vector_async(conn)


async def init_db_pool(conninfo: str | None = None) -> AsyncConnectionPool:
    """Initialize and open the module-level connection pool."""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=conninfo or settings.database_url,
            min_size=1,
            max_size=10,
            open=False,
            configure=_configure_connection,
            check=AsyncConnectionPool.check_connection,
            max_idle=120.0,
            kwargs={
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 3,
            },
        )
        await _pool.open(wait=True)
    return _pool


async def close_db_pool() -> None:
    """Close the module-level connection pool if open."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_db_pool() -> AsyncConnectionPool:
    """Return the active connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized.")
    return _pool


@asynccontextmanager
async def scoped_rls_transaction(
    ctx: RLSContext,
    pool: AsyncConnectionPool | None = None,
) -> AsyncIterator[AsyncConnection]:
    """Bind tenant/clearance claims via SET LOCAL inside an explicit transaction."""
    active_pool = pool or get_db_pool()
    async with active_pool.connection() as conn, conn.transaction():
        await conn.execute(
            "SELECT set_config('app.org_id', %s, true), "
            "set_config('app.clearance_level', %s, true), "
            "set_config('app.user_id', %s, true), "
            "set_config('app.department', %s, true), "
            "set_config('app.is_org_admin', %s, true)",
            (
                str(ctx.org_id),
                str(ctx.clearance_level),
                str(ctx.user_id),
                ctx.department,
                "true" if ctx.is_org_admin else "false",
            ),
        )
        yield conn


async def check_db_health() -> dict[str, str | bool]:
    """Verify PostgreSQL connectivity and confirm the runtime role cannot bypass RLS."""
    if _pool is None:
        return {"connected": False, "role": "uninitialized"}
    async with _pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT current_user, rolsuper, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )
        row = await cur.fetchone()
    if row is None:
        return {"connected": False, "role": "unknown"}
    role_name, is_super, bypass_rls = row
    return {
        "connected": True,
        "role": str(role_name),
        "rls_enforced": not bool(is_super) and not bool(bypass_rls),
    }
