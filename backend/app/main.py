"""FastAPI Application Entrypoint for LLM Control Center."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import analytics, auth, chat, monitoring, providers_models
from app.config import ROOT_DIR, get_settings
from app.core.errors import SecurityAndRequestMiddleware, register_exception_handlers
from app.core.security import configure_secure_logging, redact_secrets
from app.database import init_db
from app.redis_client import redis_manager
from app.services.monitoring import background_monitoring_loop

logger = logging.getLogger(__name__)

_runtime_initialized = False


async def ensure_runtime_initialized() -> None:
    global _runtime_initialized
    if _runtime_initialized:
        return
    settings = get_settings()
    configure_secure_logging(settings.log_level)
    await init_db()
    if redis_manager.client is None:
        await redis_manager.connect()
    _runtime_initialized = True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    try:
        await ensure_runtime_initialized()
    except Exception as exc:
        logger.error("Startup initialization warning: %s", redact_secrets(str(exc)))

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

    @app.middleware("http")
    async def serverless_lazy_init_middleware(request: Request, call_next):
        try:
            await ensure_runtime_initialized()
        except Exception as exc:
            logger.error(
                "Lazy runtime init failed: %s",
                redact_secrets(f"{type(exc).__name__}: {exc}"),
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "database_unavailable",
                        "message": "Database initialization failed. Check DATABASE_URL configuration.",
                    }
                },
            )
        return await call_next(request)

    app.add_middleware(SecurityAndRequestMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_origin_regex=r"https://.*\.vercel\.app",
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

    # Optional static SPA fallback if FastAPI is invoked directly for frontend routes
    dist_dir: Path = ROOT_DIR / "frontend" / "dist"
    assets_dir: Path = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", include_in_schema=False)
    async def root_entrypoint():
        index_html = dist_dir / "index.html"
        if index_html.is_file():
            return FileResponse(str(index_html), media_type="text/html")
        return {
            "service": settings.app_name,
            "status": "operational",
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
