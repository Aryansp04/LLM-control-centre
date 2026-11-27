"""Async SQLAlchemy 2.0 database engine, session factory, and health probe."""

from __future__ import annotations

import asyncio
import ssl
import time
import weakref
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
        connect_args: Dict[str, Any] = {"check_same_thread": False, "timeout": 15}
        kwargs: Dict[str, Any] = {"connect_args": connect_args}
        is_memory = ":memory:" in url
        if is_memory:
            kwargs["poolclass"] = StaticPool
        elif IS_VERCEL:
            kwargs["poolclass"] = NullPool
        engine = create_async_engine(url, future=True, **kwargs)

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            if not is_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine

    is_local_pg = "@localhost" in url or "@127.0.0.1" in url or "ssl=disable" in url
    pg_connect_args: Dict[str, Any] = {
        "statement_cache_size": 0,
        "timeout": 15,
        "command_timeout": 30,
    }
    if not is_local_pg:
        pg_connect_args["ssl"] = ssl.create_default_context()

    if IS_VERCEL:
        # Small loop-scoped pool reuses TLS/SCRAM Postgres connections across all queries in a request
        return create_async_engine(
            url,
            pool_size=2,
            max_overflow=4,
            pool_pre_ping=True,
            pool_recycle=120,
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
_loop_session_makers: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, async_sessionmaker[AsyncSession]]" = (
    weakref.WeakKeyDictionary()
)
_custom_reconfigured: bool = False
_schema_verified: bool = False


def reconfigure_database(database_url: str) -> None:
    """Rebind engine and session maker (used in isolated tests or runtime overrides)."""
    global engine, AsyncSessionLocal, _custom_reconfigured, _schema_verified
    _custom_reconfigured = True
    _schema_verified = False
    _loop_session_makers.clear()
    engine = build_engine(database_url)
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


def open_session() -> AsyncSession:
    """Always open a session bound to the current active event loop."""
    if IS_VERCEL and not _custom_reconfigured:
        try:
            loop = asyncio.get_running_loop()
            maker = _loop_session_makers.get(loop)
            if maker is None:
                loop_engine = build_engine()
                maker = async_sessionmaker(
                    bind=loop_engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autoflush=False,
                )
                _loop_session_makers[loop] = maker
            return maker()
        except RuntimeError:
            pass
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
    global _schema_verified
    if _schema_verified:
        return
    import app.models.entities  # noqa: F401

    if engine.dialect.name == "postgresql":
        async with open_session() as s:
            exists = (await s.execute(text("SELECT to_regclass('public.users')"))).scalar()
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
