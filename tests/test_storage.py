"""Tests for the storage layer using in-memory SQLite."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.models import (
    Artifact,
    PermissionRecord,
    Session,
    SessionStatus,
)
from app.storage import Storage


@pytest_asyncio.fixture
async def storage() -> Storage:
    s = Storage(":memory:")
    await s.init_db()
    yield s
    await s.close()


def _make_session(**overrides: object) -> Session:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid4(),
        status=SessionStatus.PENDING,
        title="test session",
        prompt="hello world",
        outputs_dir="/tmp/outputs",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Session(**defaults)


@pytest.mark.asyncio
async def test_create_and_retrieve_session(storage: Storage) -> None:
    session = _make_session()
    created = await storage.create_session(session)
    assert created.id == session.id

    retrieved = await storage.get_session(session.id)
    assert retrieved is not None
    assert retrieved.id == session.id
    assert retrieved.status == SessionStatus.PENDING
    assert retrieved.prompt == "hello world"
    assert retrieved.title == "test session"


@pytest.mark.asyncio
async def test_get_nonexistent_session(storage: Storage) -> None:
    result = await storage.get_session(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_update_session_status(storage: Storage) -> None:
    session = _make_session()
    await storage.create_session(session)

    updated = await storage.update_session_status(session.id, SessionStatus.RUNNING)
    assert updated is not None
    assert updated.status == SessionStatus.RUNNING
    assert updated.started_at is not None

    finished = await storage.update_session_status(
        session.id,
        SessionStatus.DONE,
        ended_at=datetime.now(timezone.utc),
    )
    assert finished is not None
    assert finished.status == SessionStatus.DONE
    assert finished.ended_at is not None


@pytest.mark.asyncio
async def test_update_session_status_with_error(storage: Storage) -> None:
    session = _make_session()
    await storage.create_session(session)

    updated = await storage.update_session_status(
        session.id,
        SessionStatus.FAILED,
        error="spawn failed",
    )
    assert updated is not None
    assert updated.status == SessionStatus.FAILED
    assert updated.error == "spawn failed"


@pytest.mark.asyncio
async def test_one_active_invariant(storage: Storage) -> None:
    s1 = _make_session()
    s2 = _make_session()
    await storage.create_session(s1)
    await storage.create_session(s2)

    await storage.update_session_status(s1.id, SessionStatus.RUNNING)

    with pytest.raises(ValueError, match="another session is already running"):
        await storage.update_session_status(s2.id, SessionStatus.RUNNING)


@pytest.mark.asyncio
async def test_list_sessions(storage: Storage) -> None:
    s1 = _make_session(status=SessionStatus.PENDING)
    s2 = _make_session(status=SessionStatus.DONE)
    await storage.create_session(s1)
    await storage.create_session(s2)

    all_sessions = await storage.list_sessions()
    assert len(all_sessions) == 2

    pending = await storage.list_sessions(status=SessionStatus.PENDING)
    assert len(pending) == 1
    assert pending[0].id == s1.id


@pytest.mark.asyncio
async def test_create_and_retrieve_artifact(storage: Storage) -> None:
    session = _make_session()
    await storage.create_session(session)

    now = datetime.now(timezone.utc)
    artifact = Artifact(
        id=uuid4(),
        session_id=session.id,
        name="report.html",
        rel_path="outputs/report.html",
        size_bytes=1024,
        content_hash="abc123",
        created_at=now,
        modified_at=now,
    )
    created = await storage.create_artifact(artifact)
    assert created.id == artifact.id

    retrieved = await storage.get_artifact(artifact.id)
    assert retrieved is not None
    assert retrieved.name == "report.html"
    assert retrieved.size_bytes == 1024


@pytest.mark.asyncio
async def test_list_artifacts_by_session(storage: Storage) -> None:
    session = _make_session()
    await storage.create_session(session)

    now = datetime.now(timezone.utc)
    for name in ["a.txt", "b.txt"]:
        artifact = Artifact(
            id=uuid4(),
            session_id=session.id,
            name=name,
            rel_path=f"outputs/{name}",
            size_bytes=100,
            content_hash=f"hash_{name}",
            created_at=now,
            modified_at=now,
        )
        await storage.create_artifact(artifact)

    artifacts = await storage.list_artifacts_by_session(session.id)
    assert len(artifacts) == 2
    assert {a.name for a in artifacts} == {"a.txt", "b.txt"}


@pytest.mark.asyncio
async def test_record_permission_denial(storage: Storage) -> None:
    session = _make_session()
    await storage.create_session(session)

    now = datetime.now(timezone.utc)
    record = PermissionRecord(
        id=0,
        session_id=session.id,
        tool_name="Bash",
        decision="deny",
        reason="tool not in allowlist",
        input={"command": "rm -rf /"},
        created_at=now,
    )
    created = await storage.record_permission(record)
    assert created.id is not None
    assert created.id > 0

    permissions = await storage.list_permissions_by_session(session.id)
    assert len(permissions) == 1
    assert permissions[0].tool_name == "Bash"
    assert permissions[0].decision == "deny"
    assert permissions[0].input == {"command": "rm -rf /"}


@pytest.mark.asyncio
async def test_record_permission_grant(storage: Storage) -> None:
    session = _make_session()
    await storage.create_session(session)

    now = datetime.now(timezone.utc)
    record = PermissionRecord(
        id=0,
        session_id=session.id,
        tool_name="Read",
        decision="grant",
        reason="tool in allowlist",
        created_at=now,
    )
    created = await storage.record_permission(record)
    assert created.decision == "grant"
