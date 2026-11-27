"""Vercel Python Serverless Entrypoint for LLM Control Center FastAPI Backend."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse

os.environ.setdefault("VERCEL", "1")

ROOT_PATH = Path(__file__).resolve().parent.parent
BACKEND_PATH = ROOT_PATH / "backend"

for candidate in (str(BACKEND_PATH), str(ROOT_PATH)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

if TYPE_CHECKING:
    import backend.app.main  # noqa: F401


def _load_asgi_app() -> FastAPI:
    try:
        from app.main import app as backend_app

        return backend_app
    except Exception as startup_exc:  # pragma: no cover - emergency diagnostic guard
        fallback = FastAPI(title="LLM Control Center Recovery")
        err_type = type(startup_exc).__name__

        @fallback.api_route(
            "/{path_name:path}",
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        )
        async def _startup_error_handler(path_name: str) -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "serverless_boot_error",
                        "message": f"Backend initialization error ({err_type}). Verify Vercel environment variables.",
                    }
                },
            )

        return fallback


app: FastAPI = _load_asgi_app()

__all__ = ["app"]
