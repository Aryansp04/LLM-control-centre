"""FastAPI Application Entrypoint for LLM Control Center."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analytics, auth, chat, monitoring, providers_models
from app.config import get_settings
from app.core.errors import SecurityAndRequestMiddleware, register_exception_handlers
from app.core.security import configure_secure_logging
from app.database import init_db
from app.redis_client import redis_manager
from app.services.monitoring import background_monitoring_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_secure_logging(settings.log_level)
    await init_db()
    await redis_manager.connect()

    stop_event = asyncio.Event()
    monitor_task: asyncio.Task | None = None
    if settings.background_monitoring_enabled:
        monitor_task = asyncio.create_task(background_monitoring_loop(stop_event))

    try:
        yield
    finally:
        stop_event.set()
        if monitor_task is not None:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        await redis_manager.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LLM Control Center API",
        description=(
            "Production-Ready Multi-Provider AI Chat, Live SSE Streaming, "
            "Real-Time Health Monitoring, and Telemetry Analytics Platform."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(SecurityAndRequestMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After", "X-RateLimit-Remaining"],
    )

    register_exception_handlers(app)

    app.include_router(auth.router)
    app.include_router(providers_models.router)
    app.include_router(chat.router)
    app.include_router(monitoring.router)
    app.include_router(analytics.router)

    return app


app = create_app()
