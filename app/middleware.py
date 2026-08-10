"""FastAPI middleware for request tracing.

Generates X-Request-ID per request, contextualizes loguru logger,
and logs request_started/request_completed with timing.
"""
from __future__ import annotations

import time
from uuid import uuid4

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestTracingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid4())
        start_time = time.monotonic()

        with logger.contextualize(request_id=request_id):
            logger.info(
                "request_started",
                method=request.method,
                path=request.url.path,
            )

            try:
                response = await call_next(request)
            except Exception:
                duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                logger.opt(exception=True).error(
                    "request_completed",
                    method=request.method,
                    path=request.url.path,
                    status_code=500,
                    duration_ms=duration_ms,
                )
                response = Response("Internal Server Error", status_code=500)
                response.headers["X-Request-ID"] = request_id
                return response

            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

        response.headers["X-Request-ID"] = request_id
        return response
