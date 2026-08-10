"""Tests for WorkspaceServer — auth, CRUD, lifecycle, memory, settings."""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from cowork.event_bus import EventBus
from cowork.models import SessionStatus
from cowork.session_manager import SessionManager
from cowork.storage import Storage
from cowork.workspace_server import create_app

TEST_TOKEN = "test-token-abc123"


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


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def _alt_auth_headers() -> dict[str, str]:
    return {"X-Workspace-Token": TEST_TOKEN}


# ---- Auth ----


async def test_no_token_returns_401(client: AsyncClient) -> None:
    r = await client.get("/api/sessions")
    assert r.status_code == 401


async def test_valid_bearer_token(client: AsyncClient) -> None:
    r = await client.get("/api/sessions", headers=_auth_headers())
    assert r.status_code == 200


async def test_valid_x_workspace_token(client: AsyncClient) -> None:
    r = await client.get("/api/sessions", headers=_alt_auth_headers())
    assert r.status_code == 200


async def test_wrong_token_returns_401(client: AsyncClient) -> None:
    r = await client.get("/api/sessions", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_health_no_auth(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---- Session CRUD ----


async def test_create_session(client: AsyncClient) -> None:
    r = await client.post(
        "/api/sessions",
        headers=_auth_headers(),
        json={"prompt": "Hello", "folder_grants": [], "allowed_tools": [], "denied_tools": []},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["prompt"] == "Hello"
    assert data["status"] == "pending"


async def test_list_sessions(client: AsyncClient) -> None:
    await client.post(
        "/api/sessions",
        headers=_auth_headers(),
        json={"prompt": "Session 1"},
    )
    r = await client.get("/api/sessions", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1


async def test_get_session_by_id(client: AsyncClient) -> None:
    cr = await client.post(
        "/api/sessions",
        headers=_auth_headers(),
        json={"prompt": "Detail test"},
    )
    session_id = cr.json()["id"]
    r = await client.get(f"/api/sessions/{session_id}", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["id"] == session_id


async def test_get_session_not_found(client: AsyncClient) -> None:
    r = await client.get(
        "/api/sessions/00000000-0000-0000-0000-000000000000",
        headers=_auth_headers(),
    )
    assert r.status_code == 404


# ---- Session lifecycle ----


async def test_archive_session(
    client: AsyncClient,
    deps: tuple[Storage, SessionManager, EventBus],
) -> None:
    storage, sm, bus = deps
    cr = await client.post(
        "/api/sessions",
        headers=_auth_headers(),
        json={"prompt": "Archive test"},
    )
    session_id = cr.json()["id"]

    from uuid import UUID
    await storage.transition(UUID(session_id), SessionStatus.RUNNING)
    await storage.transition(UUID(session_id), SessionStatus.DONE)

    r = await client.post(f"/api/sessions/{session_id}/archive", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


# ---- Events endpoint ----


async def test_events_endpoint(
    client: AsyncClient,
    deps: tuple[Storage, SessionManager, EventBus],
) -> None:
    storage, sm, bus = deps
    cr = await client.post(
        "/api/sessions",
        headers=_auth_headers(),
        json={"prompt": "Events test"},
    )
    session_id = cr.json()["id"]

    from uuid import UUID

    from cowork.models import SessionEventType
    await storage.append_event(UUID(session_id), SessionEventType.MESSAGE, {"text": "hello"})
    await storage.append_event(UUID(session_id), SessionEventType.MESSAGE, {"text": "world"})

    r = await client.get(
        f"/api/sessions/{session_id}/events?after_seq=0",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2

    r2 = await client.get(
        f"/api/sessions/{session_id}/events?after_seq=1",
        headers=_auth_headers(),
    )
    assert len(r2.json()) == 1


# ---- Memory ----


async def test_memory_get_empty(client: AsyncClient) -> None:
    with patch("cowork.workspace_server.config") as mock_config:
        mock_config.MEMORY_PATH = Path("/nonexistent/memory.md")
        mock_config.MEMORY_SIZE_CAP_BYTES = 64 * 1024
        r = await client.get("/api/memory", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == ""
    assert data["size_bytes"] == 0


async def test_memory_put_and_get(client: AsyncClient) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_path = Path(tmpdir) / "memory.md"
        with patch("cowork.workspace_server.config") as mock_config:
            mock_config.MEMORY_PATH = mem_path
            mock_config.MEMORY_SIZE_CAP_BYTES = 64 * 1024

            r = await client.put(
                "/api/memory",
                headers=_auth_headers(),
                json={"content": "remember this"},
            )
            assert r.status_code == 200
            assert r.json()["content"] == "remember this"

            r2 = await client.get("/api/memory", headers=_auth_headers())
            assert r2.status_code == 200
            assert r2.json()["content"] == "remember this"


async def test_memory_put_exceeds_cap(client: AsyncClient) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        mem_path = Path(tmpdir) / "memory.md"
        with patch("cowork.workspace_server.config") as mock_config:
            mock_config.MEMORY_PATH = mem_path
            mock_config.MEMORY_SIZE_CAP_BYTES = 10

            r = await client.put(
                "/api/memory",
                headers=_auth_headers(),
                json={"content": "a" * 20},
            )
            assert r.status_code == 413


# ---- Settings ----


async def test_settings_get(client: AsyncClient) -> None:
    r = await client.get("/api/settings", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "server_port" in data
    assert "last_boot_at" not in data


async def test_settings_put(
    client: AsyncClient,
    deps: tuple[Storage, SessionManager, EventBus],
) -> None:
    r = await client.put(
        "/api/settings",
        headers=_auth_headers(),
        json={"server_port": 9999},
    )
    assert r.status_code == 200
    assert r.json()["server_port"] == 9999

    r2 = await client.get("/api/settings", headers=_auth_headers())
    assert r2.json()["server_port"] == 9999


# ---- Tasks ----


async def test_task_crud(client: AsyncClient) -> None:
    r = await client.post(
        "/api/tasks",
        headers=_auth_headers(),
        json={"name": "Daily check", "prompt": "Run tests", "cadence": "daily"},
    )
    assert r.status_code == 201
    task_id = r.json()["id"]

    r2 = await client.get("/api/tasks", headers=_auth_headers())
    assert r2.status_code == 200
    assert any(t["id"] == task_id for t in r2.json())

    r3 = await client.patch(
        f"/api/tasks/{task_id}",
        headers=_auth_headers(),
        json={"name": "Weekly check"},
    )
    assert r3.status_code == 200
    assert r3.json()["name"] == "Weekly check"

    r4 = await client.delete(f"/api/tasks/{task_id}", headers=_auth_headers())
    assert r4.status_code == 200


# ---- Connectors ----


async def test_connector_crud(client: AsyncClient) -> None:
    r = await client.post(
        "/api/connectors",
        headers=_auth_headers(),
        json={"name": "test-mcp", "command": "/bin/test"},
    )
    assert r.status_code == 201
    conn_id = r.json()["id"]

    r2 = await client.get("/api/connectors", headers=_auth_headers())
    assert any(c["id"] == conn_id for c in r2.json())

    r3 = await client.delete(f"/api/connectors/{conn_id}", headers=_auth_headers())
    assert r3.status_code == 200
