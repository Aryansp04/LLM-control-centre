"""Structured error exceptions, handlers, HTTP security headers, and request size limits."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.core.security import redact_secrets

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class SecurityAndRequestMiddleware(BaseHTTPMiddleware):
    """Assigns X-Request-ID, enforces max request size, and sets strict security headers."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        settings = get_settings()
        incoming_req_id = request.headers.get("X-Request-ID", "").strip()
        request_id = (
            incoming_req_id
            if (incoming_req_id and len(incoming_req_id) <= 64)
            else f"req_{uuid.uuid4().hex[:20]}"
        )
        request.state.request_id = request_id

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_body_bytes:
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={
                            "error": {
                                "code": "payload_too_large",
                                "message": f"Request body exceeds limit of {settings.max_request_body_bytes} bytes.",
                                "request_id": request_id,
                            }
                        },
                        headers={"X-Request-ID": request_id},
                    )
            except ValueError:
                pass

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "media-src 'self' https://d8j0ntlcm91z4.cloudfront.net blob:; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' https: wss: ws:; "
            "frame-ancestors 'none'"
        )
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": redact_secrets(exc.message),
                    "details": exc.details,
                    "request_id": req_id,
                }
            },
            headers={"X-Request-ID": req_id},
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        detail_str = (
            exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        )
        headers = dict(exc.headers or {})
        headers["X-Request-ID"] = req_id
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": f"http_{exc.status_code}",
                    "message": redact_secrets(detail_str),
                    "request_id": req_id,
                }
            },
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        sanitized_errors = []
        field_summaries = []
        for err in exc.errors():
            loc_parts = [str(x) for x in err.get("loc", []) if x != "body"]
            field_label = ".".join(loc_parts) if loc_parts else "input"
            msg = err.get("msg", "Invalid value")
            sanitized_errors.append(
                {
                    "loc": list(err.get("loc", [])),
                    "msg": msg,
                    "type": err.get("type", "validation_error"),
                }
            )
            field_summaries.append(f"{field_label}: {msg}")
        friendly_msg = (
            "; ".join(field_summaries)
            if field_summaries
            else "Request validation failed."
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "validation_error",
                    "message": friendly_msg,
                    "details": {"fields": sanitized_errors},
                    "request_id": req_id,
                }
            },
            headers={"X-Request-ID": req_id},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        req_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "Unhandled server error [request_id=%s]: %s",
            req_id,
            redact_secrets(f"{type(exc).__name__}: {exc}"),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_server_error",
                    "message": "An unexpected internal error occurred.",
                    "request_id": req_id,
                }
            },
            headers={"X-Request-ID": req_id},
        )
