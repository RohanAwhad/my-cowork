"""Tests for SessionManager — lifecycle, event consumption, boot reconcile, memory injection."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from cowork import config
from cowork.models import (
    ProcessIdentity,
    Session,
    SessionCreate,
    SessionEventType,
    SessionStatus,
    SpawnSpec,
    StreamJsonEvent,
    UserMessage,
)
from cowork.runner_adapter import RunnerHandle
from cowork.session_manager import SessionManager
from cowork.storage import Storage


@pytest.fixture
async def storage() -> Storage:
    s = Storage(":memory:")
    await s.init()
    yield s  # type: ignore[misc]
    await s.close()


@pytest.fixture
def event_callback() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def manager(storage: Storage, event_callback: AsyncMock) -> SessionManager:
    return SessionManager(storage, event_callback)


def _make_create(prompt: str = "Write hello world") -> SessionCreate:
    return SessionCreate(prompt=prompt)


async def _insert_running_session(storage: Storage) -> Session:
    session = Session(
        id=uuid4(),
        status=SessionStatus.PENDING,
        title="existing",
        prompt="existing session",
        outputs_dir=Path("/tmp/test-outputs"),
    )
    session = await storage.insert_session(session)
    await storage.transition(session.id, SessionStatus.RUNNING)
    return await storage.get_session(session.id)  # type: ignore[return-value]


class TestCreateSession:
    async def test_creates_session_with_title_truncation(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        long_prompt = "A" * 100
        create = SessionCreate(prompt=long_prompt)

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(create)

        assert session.title == "A" * 40
        assert session.status == SessionStatus.PENDING
        assert session.prompt == long_prompt

    async def test_creates_output_dirs(
        self, manager: SessionManager, tmp_path: Path
    ) -> None:
        create = _make_create()

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(create)

        assert session.outputs_dir.exists()

    async def test_storage_insert_called(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        create = _make_create()

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(create)

        retrieved = await storage.get_session(session.id)
        assert retrieved is not None
        assert retrieved.prompt == "Write hello world"

    async def test_task_id_persisted(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        from cowork.models import ScheduledTask

        task = ScheduledTask(name="test-task", prompt="do stuff", cron_expr="0 * * * *")
        await storage.insert_task(task)

        create = _make_create()

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(create, task_id=task.id)

        assert session.task_id == task.id


class TestStartSession:
    async def test_spawns_runner_and_sends_message(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(_make_create())

        mock_handle = AsyncMock(spec=RunnerHandle)
        mock_handle.pid = 12345
        mock_handle.identity = ProcessIdentity(pid=12345, start_time_epoch=1000.0)

        async def _empty_events() -> Any:
            return
            yield  # type: ignore[misc]

        mock_handle.events.return_value = _empty_events()
        mock_handle.stderr.return_value = _empty_events()

        with patch("cowork.session_manager.spawn", return_value=mock_handle) as mock_spawn:
            await manager.start_session(session.id)

        mock_spawn.assert_called_once()
        mock_handle.send.assert_called_once()

        sent_msg = mock_handle.send.call_args[0][0]
        assert isinstance(sent_msg, UserMessage)

        updated = await storage.get_session(session.id)
        assert updated is not None
        assert updated.status == SessionStatus.RUNNING

    async def test_one_active_rejection(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        await _insert_running_session(storage)

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session2 = await manager.create_session(_make_create("second"))

        with pytest.raises(ValueError, match="One-active invariant"):
            await manager.start_session(session2.id)

    async def test_rejects_non_pending_status(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(_make_create())

        await storage.transition(session.id, SessionStatus.FAILED)

        with pytest.raises(ValueError, match="Cannot start session"):
            await manager.start_session(session.id)

    async def test_memory_injection_when_file_exists(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        memory_dir = tmp_path / "co-work"
        memory_dir.mkdir()
        memory_file = memory_dir / "memory.md"
        memory_file.write_text("Remember: user prefers concise output")

        with (
            patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"),
            patch.object(config, "MEMORY_PATH", memory_file),
            patch.object(config, "DATA_ROOT", memory_dir),
        ):
            session = await manager.create_session(_make_create())

            mock_handle = AsyncMock(spec=RunnerHandle)
            mock_handle.pid = 12345
            mock_handle.identity = ProcessIdentity(pid=12345, start_time_epoch=1000.0)

            async def _empty_events() -> Any:
                return
                yield  # type: ignore[misc]

            mock_handle.events.return_value = _empty_events()
            mock_handle.stderr.return_value = _empty_events()

            captured_spec: SpawnSpec | None = None

            async def _capture_spawn(spec: SpawnSpec) -> RunnerHandle:
                nonlocal captured_spec
                captured_spec = spec
                return mock_handle

            with patch("cowork.session_manager.spawn", side_effect=_capture_spawn):
                await manager.start_session(session.id)

        assert captured_spec is not None
        assert captured_spec.append_system_prompt is not None
        assert "Remember: user prefers concise output" in captured_spec.append_system_prompt
        assert memory_dir in captured_spec.add_dirs

    async def test_memory_injection_skipped_when_missing(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        nonexistent = tmp_path / "no-such-memory.md"

        with (
            patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"),
            patch.object(config, "MEMORY_PATH", nonexistent),
        ):
            session = await manager.create_session(_make_create())

            mock_handle = AsyncMock(spec=RunnerHandle)
            mock_handle.pid = 12345
            mock_handle.identity = ProcessIdentity(pid=12345, start_time_epoch=1000.0)

            async def _empty_events() -> Any:
                return
                yield  # type: ignore[misc]

            mock_handle.events.return_value = _empty_events()
            mock_handle.stderr.return_value = _empty_events()

            captured_spec: SpawnSpec | None = None

            async def _capture_spawn(spec: SpawnSpec) -> RunnerHandle:
                nonlocal captured_spec
                captured_spec = spec
                return mock_handle

            with patch("cowork.session_manager.spawn", side_effect=_capture_spawn):
                await manager.start_session(session.id)

        assert captured_spec is not None
        assert captured_spec.append_system_prompt is None

    async def test_memory_injection_skipped_when_over_cap(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        memory_dir = tmp_path / "co-work"
        memory_dir.mkdir()
        memory_file = memory_dir / "memory.md"
        memory_file.write_text("X" * (config.MEMORY_SIZE_CAP_BYTES + 1))

        with (
            patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"),
            patch.object(config, "MEMORY_PATH", memory_file),
            patch.object(config, "DATA_ROOT", memory_dir),
        ):
            session = await manager.create_session(_make_create())

            mock_handle = AsyncMock(spec=RunnerHandle)
            mock_handle.pid = 12345
            mock_handle.identity = ProcessIdentity(pid=12345, start_time_epoch=1000.0)

            async def _empty_events() -> Any:
                return
                yield  # type: ignore[misc]

            mock_handle.events.return_value = _empty_events()
            mock_handle.stderr.return_value = _empty_events()

            captured_spec: SpawnSpec | None = None

            async def _capture_spawn(spec: SpawnSpec) -> RunnerHandle:
                nonlocal captured_spec
                captured_spec = spec
                return mock_handle

            with patch("cowork.session_manager.spawn", side_effect=_capture_spawn):
                await manager.start_session(session.id)

        assert captured_spec is not None
        assert captured_spec.append_system_prompt is None


class TestStopSession:
    async def test_stops_handle_and_transitions(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(_make_create())

        mock_handle = AsyncMock(spec=RunnerHandle)
        mock_handle.pid = 12345
        mock_handle.identity = ProcessIdentity(pid=12345, start_time_epoch=1000.0)

        async def _empty_events() -> Any:
            return
            yield  # type: ignore[misc]

        mock_handle.events.return_value = _empty_events()
        mock_handle.stderr.return_value = _empty_events()

        with patch("cowork.session_manager.spawn", return_value=mock_handle):
            await manager.start_session(session.id)

        await manager.stop_session(session.id)

        mock_handle.stop.assert_called_once()
        updated = await storage.get_session(session.id)
        assert updated is not None
        assert updated.status == SessionStatus.STOPPED


class TestArchiveSession:
    async def test_archives_from_done(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(_make_create())

        await storage.transition(session.id, SessionStatus.RUNNING)
        await storage.transition(session.id, SessionStatus.DONE)

        await manager.archive_session(session.id)
        updated = await storage.get_session(session.id)
        assert updated is not None
        assert updated.status == SessionStatus.ARCHIVED

    async def test_archives_from_stopped(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(_make_create())

        await storage.transition(session.id, SessionStatus.RUNNING)
        await storage.transition(session.id, SessionStatus.STOPPED)

        await manager.archive_session(session.id)
        updated = await storage.get_session(session.id)
        assert updated is not None
        assert updated.status == SessionStatus.ARCHIVED

    async def test_archives_from_failed(
        self, manager: SessionManager, storage: Storage, tmp_path: Path
    ) -> None:
        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await manager.create_session(_make_create())

        await storage.transition(session.id, SessionStatus.FAILED)

        await manager.archive_session(session.id)
        updated = await storage.get_session(session.id)
        assert updated is not None
        assert updated.status == SessionStatus.ARCHIVED


class TestActiveSession:
    async def test_returns_none_when_no_running(
        self, manager: SessionManager
    ) -> None:
        result = await manager.active_session()
        assert result is None

    async def test_returns_running_session(
        self, manager: SessionManager, storage: Storage
    ) -> None:
        running = await _insert_running_session(storage)
        result = await manager.active_session()
        assert result is not None
        assert result.id == running.id


class TestEventConsumption:
    async def test_init_event_binds_cli_session_id(
        self, storage: Storage, tmp_path: Path
    ) -> None:
        callback = AsyncMock()
        mgr = SessionManager(storage, callback)

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await mgr.create_session(_make_create())

        cli_sid = "cli-session-abc"

        async def _mock_events() -> Any:
            yield StreamJsonEvent(
                type=SessionEventType.INIT.value,
                session_id=cli_sid,
                payload={"subtype": "init"},
            )

        mock_handle = AsyncMock(spec=RunnerHandle)
        mock_handle.pid = 999
        mock_handle.identity = ProcessIdentity(pid=999, start_time_epoch=500.0)
        mock_handle.events.return_value = _mock_events()

        async def _empty() -> Any:
            return
            yield  # type: ignore[misc]

        mock_handle.stderr.return_value = _empty()

        with patch("cowork.session_manager.spawn", return_value=mock_handle):
            await mgr.start_session(session.id)

        await asyncio.sleep(0.1)

        updated = await storage.get_session(session.id)
        assert updated is not None
        assert updated.cli_session_id == "init"

    async def test_result_event_transitions_to_done(
        self, storage: Storage, tmp_path: Path
    ) -> None:
        callback = AsyncMock()
        mgr = SessionManager(storage, callback)

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await mgr.create_session(_make_create())

        async def _mock_events() -> Any:
            yield StreamJsonEvent(
                type=SessionEventType.RESULT.value,
                payload={"num_turns": 3, "is_error": False},
            )

        mock_handle = AsyncMock(spec=RunnerHandle)
        mock_handle.pid = 999
        mock_handle.identity = ProcessIdentity(pid=999, start_time_epoch=500.0)
        mock_handle.events.return_value = _mock_events()

        async def _empty() -> Any:
            return
            yield  # type: ignore[misc]

        mock_handle.stderr.return_value = _empty()

        with patch("cowork.session_manager.spawn", return_value=mock_handle):
            await mgr.start_session(session.id)

        await asyncio.sleep(0.1)

        updated = await storage.get_session(session.id)
        assert updated is not None
        assert updated.status == SessionStatus.DONE
        assert updated.num_turns == 3
        assert updated.is_error is False

    async def test_error_event_transitions_to_failed(
        self, storage: Storage, tmp_path: Path
    ) -> None:
        callback = AsyncMock()
        mgr = SessionManager(storage, callback)

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await mgr.create_session(_make_create())

        async def _mock_events() -> Any:
            yield StreamJsonEvent(
                type=SessionEventType.ERROR.value,
                payload={"error": "auth expired"},
            )

        mock_handle = AsyncMock(spec=RunnerHandle)
        mock_handle.pid = 999
        mock_handle.identity = ProcessIdentity(pid=999, start_time_epoch=500.0)
        mock_handle.events.return_value = _mock_events()

        async def _empty() -> Any:
            return
            yield  # type: ignore[misc]

        mock_handle.stderr.return_value = _empty()

        with patch("cowork.session_manager.spawn", return_value=mock_handle):
            await mgr.start_session(session.id)

        await asyncio.sleep(0.1)

        updated = await storage.get_session(session.id)
        assert updated is not None
        assert updated.status == SessionStatus.FAILED
        assert updated.error == "auth expired"

    async def test_events_persisted_to_storage(
        self, storage: Storage, tmp_path: Path
    ) -> None:
        callback = AsyncMock()
        mgr = SessionManager(storage, callback)

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await mgr.create_session(_make_create())

        async def _mock_events() -> Any:
            yield StreamJsonEvent(
                type=SessionEventType.MESSAGE.value,
                payload={"content": "hello"},
                raw='{"type":"assistant","content":"hello"}',
            )

        mock_handle = AsyncMock(spec=RunnerHandle)
        mock_handle.pid = 999
        mock_handle.identity = ProcessIdentity(pid=999, start_time_epoch=500.0)
        mock_handle.events.return_value = _mock_events()

        async def _empty() -> Any:
            return
            yield  # type: ignore[misc]

        mock_handle.stderr.return_value = _empty()

        with patch("cowork.session_manager.spawn", return_value=mock_handle):
            await mgr.start_session(session.id)

        await asyncio.sleep(0.1)

        events = await storage.list_events(session.id)
        assert len(events) >= 1
        assert events[0].event_type == SessionEventType.MESSAGE

    async def test_event_callback_invoked(
        self, storage: Storage, tmp_path: Path
    ) -> None:
        callback = AsyncMock()
        mgr = SessionManager(storage, callback)

        with patch.object(config, "SESSIONS_DIR", tmp_path / "sessions"):
            session = await mgr.create_session(_make_create())

        async def _mock_events() -> Any:
            yield StreamJsonEvent(
                type=SessionEventType.MESSAGE.value,
                payload={"content": "hi"},
            )

        mock_handle = AsyncMock(spec=RunnerHandle)
        mock_handle.pid = 999
        mock_handle.identity = ProcessIdentity(pid=999, start_time_epoch=500.0)
        mock_handle.events.return_value = _mock_events()

        async def _empty() -> Any:
            return
            yield  # type: ignore[misc]

        mock_handle.stderr.return_value = _empty()

        with patch("cowork.session_manager.spawn", return_value=mock_handle):
            await mgr.start_session(session.id)

        await asyncio.sleep(0.1)

        callback.assert_called()
        call_args = callback.call_args[0]
        assert call_args[0] == "session.event"


class TestReconcile:
    async def test_stale_running_sessions_marked_failed(
        self, manager: SessionManager, storage: Storage
    ) -> None:
        session = await _insert_running_session(storage)

        cutoff = datetime.now(UTC) + timedelta(hours=1)
        with patch("cowork.session_manager.probe", return_value=False):
            await manager.reconcile(cutoff)

        updated = await storage.get_session(session.id)
        assert updated is not None
        assert updated.status == SessionStatus.FAILED

    async def test_reconcile_kills_alive_orphans(
        self, manager: SessionManager, storage: Storage
    ) -> None:
        session = Session(
            id=uuid4(),
            status=SessionStatus.PENDING,
            title="orphan",
            prompt="orphan prompt",
            outputs_dir=Path("/tmp/test"),
            process_identity=ProcessIdentity(pid=99999, start_time_epoch=1000.0),
        )
        await storage.insert_session(session)
        await storage.transition(session.id, SessionStatus.RUNNING)

        cutoff = datetime.now(UTC) + timedelta(hours=1)
        with (
            patch("cowork.session_manager.probe", return_value=True),
            patch("cowork.session_manager.process_group_kill") as mock_kill,
        ):
            await manager.reconcile(cutoff)

        mock_kill.assert_called_once()
