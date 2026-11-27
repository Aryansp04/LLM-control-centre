"""Async SQLAlchemy 2.0 database engine, session factory, and health probe."""

from __future__ import annotations

import ssl
import time
from typing import Any, AsyncGenerator, Dict, Optional

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, StaticPool

from app.config import IS_VERCEL, get_settings


class Base(DeclarativeBase):
    """Declarative base for all 10 PostgreSQL entities."""


_SSL_CTX: Optional[ssl.SSLContext] = None


def _get_ssl_context() -> ssl.SSLContext:
    global _SSL_CTX
    if _SSL_CTX is None:
        _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX


def build_engine(database_url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    url = database_url or settings.database_url

    if url.startswith("sqlite"):
        connect_args: Dict[str, Any] = {"check_same_thread": False, "timeout": 15}
        kwargs: Dict[str, Any] = {"connect_args": connect_args}
        is_memory = ":memory:" in url
        if is_memory:
            kwargs["poolclass"] = StaticPool
        elif IS_VERCEL:
            kwargs["poolclass"] = NullPool
        engine_inst = create_async_engine(url, future=True, **kwargs)

        @event.listens_for(engine_inst.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            if not is_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine_inst

    is_local_pg = "@localhost" in url or "@127.0.0.1" in url or "ssl=disable" in url
    pg_connect_args: Dict[str, Any] = {
        "statement_cache_size": 0,
        "timeout": 10,
        "command_timeout": 25,
    }
    if not is_local_pg:
        pg_connect_args["ssl"] = _get_ssl_context()

    if IS_VERCEL:
        # NullPool avoids cross-event-loop and frozen-Lambda socket hangs (~45ms inside iad1)
        return create_async_engine(
            url,
            poolclass=NullPool,
            connect_args=pg_connect_args,
            future=True,
        )

    return create_async_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args=pg_connect_args,
        future=True,
    )


engine: AsyncEngine = build_engine()
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
_schema_verified: bool = False


def reconfigure_database(database_url: str) -> None:
    """Rebind engine and session maker (used in isolated tests or runtime overrides)."""
    global engine, AsyncSessionLocal, _schema_verified
    _schema_verified = False
    engine = build_engine(database_url)
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


def open_session() -> AsyncSession:
    """Always open a session from the active `AsyncSessionLocal` factory."""
    return AsyncSessionLocal()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with open_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Ensure schema exists once per process."""
    global _schema_verified
    if _schema_verified:
        return
    import app.models.entities  # noqa: F401

    if engine.dialect.name == "postgresql":
        async with open_session() as s:
            exists = (
                await s.execute(text("SELECT to_regclass('public.users')"))
            ).scalar()
            if exists is not None:
                _schema_verified = True
                return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _schema_verified = True


async def check_database_health() -> Dict[str, Any]:
    """Execute a live round-trip query against the database and measure latency."""
    started = time.perf_counter()
    dialect_name = engine.dialect.name
    try:
        async with open_session() as session:
            await session.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return {
            "status": "operational",
            "healthy": True,
            "dialect": dialect_name,
            "latency_ms": latency_ms,
            "error": None,
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return {
            "status": "unavailable",
            "healthy": False,
            "dialect": dialect_name,
            "latency_ms": latency_ms,
            "error": f"Database connectivity check failed ({type(exc).__name__})",
        }
