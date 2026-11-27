"""Async SQLAlchemy 2.0 database engine, session factory, and health probe."""

from __future__ import annotations

import time
from typing import Any, AsyncGenerator, Dict

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


def build_engine(database_url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    url = database_url or settings.database_url

    if url.startswith("sqlite"):
        connect_args: Dict[str, Any] = {"check_same_thread": False}
        kwargs: Dict[str, Any] = {"connect_args": connect_args}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        elif IS_VERCEL:
            kwargs["poolclass"] = NullPool
        engine = create_async_engine(url, future=True, **kwargs)

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    if IS_VERCEL:
        # Use NullPool on serverless functions to avoid cross-event-loop asyncpg pool errors
        return create_async_engine(url, poolclass=NullPool, future=True)

    return create_async_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        future=True,
    )


engine: AsyncEngine = build_engine()
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def reconfigure_database(database_url: str) -> None:
    """Rebind engine and session maker (used in isolated tests or runtime overrides)."""
    global engine, AsyncSessionLocal
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
    """Ensure schema exists when starting up in standalone or test environments."""
    import app.models.entities  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_database_health() -> Dict[str, Any]:
    """Execute a live round-trip query against the database and measure latency."""
    started = time.perf_counter()
    dialect_name = engine.dialect.name
    try:
        async with AsyncSessionLocal() as session:
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
