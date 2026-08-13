from __future__ import annotations

import contextvars
import json
import logging
import os
from datetime import UTC, datetime
from uuid import uuid4

import redis
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from clinical_data_platform.celery_app import REDIS_URL, WORKER_HEARTBEAT_KEY
from clinical_data_platform.session import SessionLocal

request_id_context = contextvars.ContextVar("request_id", default=None)


class RequestBodyTooLarge(Exception):
    """Raised before an application handler can consume an oversized body."""


class ContentSizeLimitMiddleware:
    """Enforce a byte limit for both Content-Length and chunked requests.

    Reverse proxies should apply the same (or stricter) limit. This guard is
    still required because a client can omit Content-Length and stream a body.
    """

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope, receive, send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": f"request body exceeds configured limit of {self.max_bytes} bytes"},
        )
        await response(scope, receive, send)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        for field in ("import_job_id", "import_status", "method", "path", "status_code", "duration_ms"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        import time

        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logging.getLogger("clinical_data_platform.request").info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return response
        finally:
            request_id_context.reset(token)


def readiness_checks() -> dict[str, dict[str, str]]:
    checks = {}
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)}

    try:
        redis_client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        redis_client.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as exc:
        checks["redis"] = {"status": "error", "detail": str(exc)}

    if checks["redis"]["status"] == "error":
        checks["worker"] = {"status": "error", "detail": "check blocked by Redis failure"}
    elif redis_client.get(WORKER_HEARTBEAT_KEY):
        checks["worker"] = {"status": "ok"}
    else:
        checks["worker"] = {"status": "error", "detail": "no recent worker heartbeat"}
    return checks
