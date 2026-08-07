"""Tests for RequestTracingMiddleware including error path."""
from __future__ import annotations

import json
from io import StringIO

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from loguru import logger

from app.middleware import RequestTracingMiddleware


def _capture_logs() -> StringIO:
    buf = StringIO()

    def _sink(message: object) -> None:
        record = message.record  # type: ignore[union-attr]
        entry = {
            "level": record["level"].name,
            "message": record["message"],
        }
        extras = {k: v for k, v in record["extra"].items() if not k.startswith("_")}
        if extras:
            entry["extras"] = extras
        if record["exception"] is not None:
            entry["exception"] = True
        buf.write(json.dumps(entry) + "\n")

    logger.remove()
    logger.add(_sink, level="DEBUG", format="{message}")
    return buf


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestTracingMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    return app


@pytest.mark.asyncio
async def test_happy_path_request_id_header() -> None:
    _capture_logs()
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ping")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 36
    logger.remove()


@pytest.mark.asyncio
async def test_happy_path_logs_start_and_complete() -> None:
    buf = _capture_logs()
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/ping")

    lines = [json.loads(l) for l in buf.getvalue().strip().split("\n") if l.strip()]
    messages = [l["message"] for l in lines]
    assert "request_started" in messages
    assert "request_completed" in messages

    completed = next(l for l in lines if l["message"] == "request_completed")
    assert completed["extras"]["status_code"] == 200
    assert "duration_ms" in completed["extras"]
    assert "request_id" in completed["extras"]
    logger.remove()


@pytest.mark.asyncio
async def test_error_path_returns_500_with_request_id() -> None:
    _capture_logs()
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/boom")
    assert response.status_code == 500
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 36
    logger.remove()


@pytest.mark.asyncio
async def test_error_path_logs_completed_with_500() -> None:
    buf = _capture_logs()
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/boom")

    lines = [json.loads(l) for l in buf.getvalue().strip().split("\n") if l.strip()]
    messages = [l["message"] for l in lines]
    assert "request_started" in messages
    assert "request_completed" in messages

    completed = next(l for l in lines if l["message"] == "request_completed")
    assert completed["extras"]["status_code"] == 500
    assert completed["level"] == "ERROR"
    assert completed.get("exception") is True
    logger.remove()
