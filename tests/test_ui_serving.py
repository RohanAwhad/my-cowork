"""Tests for static UI serving — index, static files, auth, health."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from cowork.event_bus import EventBus
from cowork.session_manager import SessionManager
from cowork.storage import Storage
from cowork.workspace_server import create_app

TEST_TOKEN = "test-ui-token-xyz789"


@pytest.fixture
async def deps() -> AsyncIterator[tuple[Storage, SessionManager, EventBus]]:
    storage = Storage(":memory:")
    await storage.init()
    bus = EventBus()
    sm = SessionManager(storage)
    yield storage, sm, bus
    await storage.close()


@pytest.fixture
async def client(deps: tuple[Storage, SessionManager, EventBus]) -> AsyncIterator[AsyncClient]:
    storage, sm, bus = deps
    app = create_app(storage, sm, bus, server_token=TEST_TOKEN)
    transport = ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


async def test_index_returns_html(client: AsyncClient) -> None:
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Co-work" in r.text


async def test_static_js_serves(client: AsyncClient) -> None:
    r = await client.get("/static/app.js")
    assert r.status_code == 200
    body = r.text
    assert "getToken" in body or "function" in body


async def test_static_css_serves(client: AsyncClient) -> None:
    r = await client.get("/static/style.css")
    assert r.status_code == 200
    assert "background" in r.text


async def test_static_no_auth_required(client: AsyncClient) -> None:
    r = await client.get("/static/app.js")
    assert r.status_code == 200


async def test_api_rejects_without_token(client: AsyncClient) -> None:
    r = await client.get("/api/sessions")
    assert r.status_code == 401


async def test_api_accepts_with_token(client: AsyncClient) -> None:
    r = await client.get("/api/sessions", headers=_auth())
    assert r.status_code == 200


async def test_health_no_auth(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_index_no_auth_needed(client: AsyncClient) -> None:
    r = await client.get("/")
    assert r.status_code == 200
