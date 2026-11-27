"""Isolated test fixtures using in-memory SQLAlchemy async DB and FakeRedis.

Clearly separates mocked unit/component tests from `@pytest.mark.live_provider` tests.
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ["APP_ENV"] = "test"
os.environ["BACKGROUND_MONITORING_ENABLED"] = "false"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "memory://test"
os.environ["JWT_SECRET_KEY"] = "test-only-jwt-secret-key-0123456789abcdef0123456789abcdef"
os.environ["ENCRYPTION_SECRET_KEY"] = "test-only-encryption-secret-key-32bytes"

from app.config import get_settings

get_settings.cache_clear()

import app.database as db_module
from app.main import create_app
from app.redis_client import redis_manager


@pytest_asyncio.fixture()
async def app_instance(monkeypatch):
    # Ensure isolated unit tests never accidentally hit external provider APIs
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    db_module.reconfigure_database("sqlite+aiosqlite:///:memory:")
    await db_module.init_db()
    await redis_manager.connect("memory://test")
    redis_manager._fallback_kv.clear()
    redis_manager._fallback_rate.clear()
    redis_manager._active_generations.clear()
    redis_manager._cancel_events.clear()

    application = create_app()
    yield application

    await redis_manager.close()
    await db_module.engine.dispose()


@pytest_asyncio.fixture()
async def client(app_instance) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
