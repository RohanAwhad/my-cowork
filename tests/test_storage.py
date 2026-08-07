"""Tests for the Storage layer — async, in-memory SQLite."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from cowork.models import (
    Connector,
    PermissionDecision,
    ScheduledTask,
    Session,
    SessionEventType,
    SessionStatus,
    TaskStatus,
)
from cowork.storage import Storage


@pytest.fixture
async def storage() -> AsyncIterator[Storage]:
    s = Storage(":memory:")
    await s.init()
    yield s
    await s.close()


def _make_session(**overrides: object) -> Session:
    defaults: dict[str, object] = {
        "prompt": "do something",
        "outputs_dir": Path("/tmp/outputs"),
    }
    defaults.update(overrides)
    return Session(**defaults)  # type: ignore[arg-type]


# ------------------------------------------------------------------
# Session CRUD
# ------------------------------------------------------------------


class TestSessionCrud:
    async def test_insert_and_get(self, storage: Storage) -> None:
        s = _make_session()
        inserted = await storage.insert_session(s)
        assert inserted.id == s.id

        fetched = await storage.get_session(s.id)
        assert fetched is not None
        assert fetched.id == s.id
        assert fetched.prompt == "do something"
        assert fetched.status == SessionStatus.PENDING

    async def test_get_nonexistent(self, storage: Storage) -> None:
        result = await storage.get_session(uuid4())
        assert result is None

    async def test_list_returns_summary_with_artifact_count(self, storage: Storage) -> None:
        s = _make_session(title="my session")
        await storage.insert_session(s)

        await storage.record_artifact(
            session_id=s.id,
            name="file.txt",
            rel_path="file.txt",
            content_hash="abc",
            size_bytes=100,
            stored_rel_path="artifacts/file__v1_abc.txt",
        )

        summaries = await storage.list_sessions()
        assert len(summaries) == 1
        assert summaries[0].id == s.id
        assert summaries[0].title == "my session"
        assert summaries[0].artifact_count == 1

    async def test_update_session(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        updated = await storage.update_session(s.id, cli_session_id="cli-999", num_turns=5)
        assert updated.cli_session_id == "cli-999"
        assert updated.num_turns == 5

    async def test_json_columns_roundtrip(self, storage: Storage) -> None:
        s = _make_session(
            allowed_tools=["Read", "Write"],
            denied_tools=["Bash"],
            mcp_config={"server": {"command": "npx"}},
            user_selected_folders=[Path("/home/user/project")],
        )
        await storage.insert_session(s)

        fetched = await storage.get_session(s.id)
        assert fetched is not None
        assert fetched.allowed_tools == ["Read", "Write"]
        assert fetched.denied_tools == ["Bash"]
        assert fetched.mcp_config == {"server": {"command": "npx"}}
        assert fetched.user_selected_folders == [Path("/home/user/project")]


# ------------------------------------------------------------------
# Session transitions
# ------------------------------------------------------------------


class TestSessionTransitions:
    async def test_legal_transition_pending_to_running(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)
        result = await storage.transition(s.id, SessionStatus.RUNNING)
        assert result.status == SessionStatus.RUNNING
        assert result.started_at is not None

    async def test_illegal_transition_pending_to_done(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)
        with pytest.raises(ValueError, match="Illegal transition"):
            await storage.transition(s.id, SessionStatus.DONE)

    async def test_illegal_transition_running_to_pending(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)
        await storage.transition(s.id, SessionStatus.RUNNING)
        with pytest.raises(ValueError, match="Illegal transition"):
            await storage.transition(s.id, SessionStatus.PENDING)

    async def test_one_active_invariant(self, storage: Storage) -> None:
        s1 = _make_session()
        s2 = _make_session()
        await storage.insert_session(s1)
        await storage.insert_session(s2)

        await storage.transition(s1.id, SessionStatus.RUNNING)

        with pytest.raises(ValueError, match="One-active invariant"):
            await storage.transition(s2.id, SessionStatus.RUNNING)

    async def test_transition_to_done_sets_ended_at(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)
        await storage.transition(s.id, SessionStatus.RUNNING)
        result = await storage.transition(s.id, SessionStatus.DONE)
        assert result.status == SessionStatus.DONE
        assert result.ended_at is not None

    async def test_transition_nonexistent_session(self, storage: Storage) -> None:
        with pytest.raises(ValueError, match="not found"):
            await storage.transition(uuid4(), SessionStatus.RUNNING)

    async def test_full_lifecycle(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)
        await storage.transition(s.id, SessionStatus.RUNNING)
        await storage.transition(s.id, SessionStatus.DONE)
        result = await storage.transition(s.id, SessionStatus.ARCHIVED)
        assert result.status == SessionStatus.ARCHIVED


# ------------------------------------------------------------------
# Reconcile running
# ------------------------------------------------------------------


class TestReconcileRunning:
    async def test_reconcile_sets_failed(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)
        await storage.transition(s.id, SessionStatus.RUNNING)

        future_cutoff = datetime.now(UTC) + timedelta(hours=1)
        await storage.reconcile_running(future_cutoff)

        fetched = await storage.get_session(s.id)
        assert fetched is not None
        assert fetched.status == SessionStatus.FAILED

    async def test_reconcile_ignores_recent(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)
        await storage.transition(s.id, SessionStatus.RUNNING)

        past_cutoff = datetime(2000, 1, 1, tzinfo=UTC)
        await storage.reconcile_running(past_cutoff)

        fetched = await storage.get_session(s.id)
        assert fetched is not None
        assert fetched.status == SessionStatus.RUNNING


# ------------------------------------------------------------------
# Events
# ------------------------------------------------------------------


class TestEvents:
    async def test_append_and_list(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        ev1 = await storage.append_event(s.id, SessionEventType.INIT, {"session_id": "abc"})
        ev2 = await storage.append_event(s.id, SessionEventType.MESSAGE, {"kind": "assistant"})

        assert ev1.seq == 1
        assert ev2.seq == 2

        events = await storage.list_events(s.id)
        assert len(events) == 2
        assert events[0].seq == 1
        assert events[1].seq == 2

    async def test_list_after_seq(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        await storage.append_event(s.id, SessionEventType.INIT, {})
        await storage.append_event(s.id, SessionEventType.MESSAGE, {})
        await storage.append_event(s.id, SessionEventType.RESULT, {"num_turns": 1})

        events = await storage.list_events(s.id, after_seq=1)
        assert len(events) == 2
        assert events[0].seq == 2

    async def test_seq_increments_correctly(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        seqs = []
        for i in range(5):
            ev = await storage.append_event(s.id, SessionEventType.MESSAGE, {"i": i})
            seqs.append(ev.seq)

        assert seqs == [1, 2, 3, 4, 5]


# ------------------------------------------------------------------
# Tasks
# ------------------------------------------------------------------


class TestTaskCrud:
    async def test_insert_and_get(self, storage: Storage) -> None:
        t = ScheduledTask(name="daily check", cadence="daily", prompt="run checks")
        await storage.insert_task(t)

        fetched = await storage.get_task(t.id)
        assert fetched is not None
        assert fetched.name == "daily check"
        assert fetched.cadence == "daily"
        assert fetched.status == TaskStatus.ACTIVE

    async def test_get_nonexistent(self, storage: Storage) -> None:
        result = await storage.get_task(uuid4())
        assert result is None

    async def test_list_tasks(self, storage: Storage) -> None:
        t1 = ScheduledTask(name="task1", cadence="hourly", prompt="p1")
        t2 = ScheduledTask(name="task2", cron_expr="*/5 * * * *", prompt="p2")
        await storage.insert_task(t1)
        await storage.insert_task(t2)

        tasks = await storage.list_tasks()
        assert len(tasks) == 2

    async def test_update_task(self, storage: Storage) -> None:
        t = ScheduledTask(name="test", cadence="daily", prompt="p")
        await storage.insert_task(t)

        updated = await storage.update_task(t.id, name="updated name")
        assert updated.name == "updated name"

    async def test_set_task_status(self, storage: Storage) -> None:
        t = ScheduledTask(name="test", cadence="daily", prompt="p")
        await storage.insert_task(t)

        result = await storage.set_task_status(t.id, TaskStatus.PAUSED)
        assert result.status == TaskStatus.PAUSED

    async def test_list_due(self, storage: Storage) -> None:
        past = datetime.now(UTC) - timedelta(minutes=5)
        future = datetime.now(UTC) + timedelta(hours=1)

        t_due = ScheduledTask(name="due", cadence="hourly", prompt="p", next_run_at=past)
        t_not_due = ScheduledTask(name="not-due", cadence="hourly", prompt="p", next_run_at=future)
        t_paused = ScheduledTask(
            name="paused", cadence="hourly", prompt="p",
            next_run_at=past, status=TaskStatus.PAUSED,
        )
        await storage.insert_task(t_due)
        await storage.insert_task(t_not_due)
        await storage.insert_task(t_paused)

        now = datetime.now(UTC)
        due = await storage.list_due(now)
        assert len(due) == 1
        assert due[0].id == t_due.id


# ------------------------------------------------------------------
# Artifacts
# ------------------------------------------------------------------


class TestArtifacts:
    async def test_record_creates_artifact_and_version(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        artifact, version = await storage.record_artifact(
            session_id=s.id,
            name="report.pdf",
            rel_path="report.pdf",
            content_hash="sha256abc",
            size_bytes=2048,
            stored_rel_path="artifacts/report__v1_sha256ab.pdf",
        )

        assert artifact.name == "report.pdf"
        assert artifact.current_version == 1
        assert version.version == 1
        assert version.content_hash == "sha256abc"

    async def test_record_bumps_version(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        a1, v1 = await storage.record_artifact(
            session_id=s.id,
            name="data.csv",
            rel_path="data.csv",
            content_hash="hash_v1",
            size_bytes=100,
            stored_rel_path="artifacts/data__v1_hash_v1.csv",
        )
        assert a1.current_version == 1
        assert v1.version == 1

        a2, v2 = await storage.record_artifact(
            session_id=s.id,
            name="data.csv",
            rel_path="data.csv",
            content_hash="hash_v2",
            size_bytes=200,
            stored_rel_path="artifacts/data__v2_hash_v2.csv",
        )
        assert a2.current_version == 2
        assert a2.id == a1.id
        assert v2.version == 2
        assert a2.content_hash == "hash_v2"

    async def test_list_artifacts(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        await storage.record_artifact(
            session_id=s.id, name="a.txt", rel_path="a.txt",
            content_hash="h1", size_bytes=10, stored_rel_path="artifacts/a__v1.txt",
        )
        await storage.record_artifact(
            session_id=s.id, name="b.txt", rel_path="b.txt",
            content_hash="h2", size_bytes=20, stored_rel_path="artifacts/b__v1.txt",
        )

        artifacts = await storage.list_artifacts(s.id)
        assert len(artifacts) == 2

    async def test_get_artifact(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        artifact, _ = await storage.record_artifact(
            session_id=s.id, name="x.txt", rel_path="x.txt",
            content_hash="hx", size_bytes=5, stored_rel_path="artifacts/x__v1.txt",
        )

        fetched = await storage.get_artifact(artifact.id)
        assert fetched is not None
        assert fetched.name == "x.txt"

        assert await storage.get_artifact(uuid4()) is None


# ------------------------------------------------------------------
# Permissions
# ------------------------------------------------------------------


class TestPermissions:
    async def test_append_and_list(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        rec = await storage.append_permission(
            session_id=s.id,
            task_id=None,
            tool_name="Read",
            decision=PermissionDecision.GRANT,
            reason="in allowlist",
            input_data={"path": "/tmp/file"},
        )
        assert rec.tool_name == "Read"
        assert rec.decision == PermissionDecision.GRANT

        perms = await storage.list_permissions(s.id)
        assert len(perms) == 1
        assert perms[0].tool_name == "Read"
        assert perms[0].input == {"path": "/tmp/file"}

    async def test_multiple_permissions(self, storage: Storage) -> None:
        s = _make_session()
        await storage.insert_session(s)

        await storage.append_permission(
            session_id=s.id, task_id=None, tool_name="Read",
            decision=PermissionDecision.GRANT, reason="allowed", input_data={},
        )
        await storage.append_permission(
            session_id=s.id, task_id=None, tool_name="Bash",
            decision=PermissionDecision.DENY, reason="denied", input_data={"command": "rm -rf /"},
        )

        perms = await storage.list_permissions(s.id)
        assert len(perms) == 2


# ------------------------------------------------------------------
# Connectors
# ------------------------------------------------------------------


class TestConnectorCrud:
    async def test_insert_and_get(self, storage: Storage) -> None:
        c = Connector(name="github", command="npx", args=["-y", "@github/mcp"])
        await storage.insert_connector(c)

        fetched = await storage.get_connector(c.id)
        assert fetched is not None
        assert fetched.name == "github"
        assert fetched.command == "npx"
        assert fetched.args == ["-y", "@github/mcp"]

    async def test_get_nonexistent(self, storage: Storage) -> None:
        assert await storage.get_connector(uuid4()) is None

    async def test_list_connectors(self, storage: Storage) -> None:
        c1 = Connector(name="a", command="cmd1")
        c2 = Connector(name="b", command="cmd2")
        await storage.insert_connector(c1)
        await storage.insert_connector(c2)

        connectors = await storage.list_connectors()
        assert len(connectors) == 2

    async def test_update_connector(self, storage: Storage) -> None:
        c = Connector(name="test", command="cmd")
        await storage.insert_connector(c)

        updated = await storage.update_connector(c.id, name="updated")
        assert updated.name == "updated"

    async def test_delete_connector(self, storage: Storage) -> None:
        c = Connector(name="to-delete", command="cmd")
        await storage.insert_connector(c)

        await storage.delete_connector(c.id)
        assert await storage.get_connector(c.id) is None

        connectors = await storage.list_connectors()
        assert len(connectors) == 0


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------


class TestSettings:
    async def test_get_set(self, storage: Storage) -> None:
        await storage.set_setting("server_port", "8765")
        val = await storage.get_setting("server_port")
        assert val == "8765"

    async def test_get_default(self, storage: Storage) -> None:
        val = await storage.get_setting("nonexistent", default="fallback")
        assert val == "fallback"

    async def test_get_no_default(self, storage: Storage) -> None:
        val = await storage.get_setting("nonexistent")
        assert val is None

    async def test_upsert(self, storage: Storage) -> None:
        await storage.set_setting("key", "v1")
        await storage.set_setting("key", "v2")
        val = await storage.get_setting("key")
        assert val == "v2"
