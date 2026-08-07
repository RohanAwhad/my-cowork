"""Tests for pydantic entity models — validation, enums, defaults."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cowork.models import (
    Artifact,
    ArtifactVersion,
    Connector,
    ConnectorStatus,
    EffectivePolicy,
    MemorySnapshot,
    PermissionDecision,
    PermissionRecord,
    ProcessIdentity,
    ScheduledTask,
    Session,
    SessionCreate,
    SessionEvent,
    SessionEventType,
    SessionStatus,
    SessionSummary,
    Settings,
    SpawnSpec,
    StreamJsonEvent,
    TaskStatus,
    UserMessage,
)


class TestSessionStatus:
    def test_all_values(self) -> None:
        expected = {"pending", "queued", "running", "done", "stopped", "failed", "archived"}
        assert {s.value for s in SessionStatus} == expected

    def test_str_enum(self) -> None:
        assert str(SessionStatus.RUNNING) == "running"
        assert SessionStatus("pending") == SessionStatus.PENDING


class TestTaskStatus:
    def test_all_values(self) -> None:
        expected = {"active", "paused", "disabled", "missed", "queued"}
        assert {s.value for s in TaskStatus} == expected


class TestPermissionDecision:
    def test_all_values(self) -> None:
        expected = {"grant", "deny", "approve_future", "deleted_observed"}
        assert {d.value for d in PermissionDecision} == expected


class TestProcessIdentity:
    def test_creation(self) -> None:
        pi = ProcessIdentity(pid=1234, start_time_epoch=1700000000.0)
        assert pi.pid == 1234
        assert pi.start_time_epoch == 1700000000.0

    def test_equality(self) -> None:
        pi1 = ProcessIdentity(pid=1234, start_time_epoch=1700000000.0)
        pi2 = ProcessIdentity(pid=1234, start_time_epoch=1700000000.0)
        assert pi1 == pi2

    def test_inequality_different_pid(self) -> None:
        pi1 = ProcessIdentity(pid=1234, start_time_epoch=1700000000.0)
        pi2 = ProcessIdentity(pid=5678, start_time_epoch=1700000000.0)
        assert pi1 != pi2

    def test_inequality_different_epoch(self) -> None:
        pi1 = ProcessIdentity(pid=1234, start_time_epoch=1700000000.0)
        pi2 = ProcessIdentity(pid=1234, start_time_epoch=1700000001.0)
        assert pi1 != pi2


class TestSession:
    def test_defaults(self) -> None:
        s = Session(prompt="do something")
        assert s.status == SessionStatus.PENDING
        assert s.title == ""
        assert s.transcript_source == "stream-json"
        assert s.mcp_config == {}
        assert s.allowed_tools == []
        assert s.denied_tools == []
        assert s.user_selected_folders == []
        assert s.cli_session_id is None
        assert s.error is None
        assert s.task_id is None
        assert s.process_identity is None
        assert s.started_at is None
        assert s.ended_at is None
        assert s.id is not None
        assert s.created_at is not None

    def test_full_construction(self) -> None:
        sid = uuid4()
        now = datetime.now(UTC)
        s = Session(
            id=sid,
            status=SessionStatus.RUNNING,
            title="Test session",
            prompt="build a thing",
            mcp_config={"server1": {"command": "npx"}},
            allowed_tools=["Read", "Write"],
            denied_tools=["Bash"],
            user_selected_folders=[Path("/Users/test/project")],
            outputs_dir=Path("/tmp/outputs"),
            cli_session_id="cli-123",
            process_identity=ProcessIdentity(pid=999, start_time_epoch=1700000000.0),
            created_at=now,
            updated_at=now,
            started_at=now,
        )
        assert s.id == sid
        assert s.status == SessionStatus.RUNNING
        assert s.allowed_tools == ["Read", "Write"]
        assert s.process_identity is not None
        assert s.process_identity.pid == 999

    def test_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            Session(prompt="test", status="invalid_status")  # type: ignore[arg-type]


class TestSessionEvent:
    def test_creation(self) -> None:
        sid = uuid4()
        ev = SessionEvent(
            session_id=sid,
            seq=1,
            event_type=SessionEventType.INIT,
            payload={"cli_session_id": "abc"},
        )
        assert ev.session_id == sid
        assert ev.seq == 1
        assert ev.event_type == SessionEventType.INIT

    def test_all_event_types(self) -> None:
        expected = {
            "init", "message", "user", "tool_use", "tool_result",
            "result", "error", "close", "init_status", "raw",
        }
        assert {e.value for e in SessionEventType} == expected


class TestScheduledTask:
    def test_with_cadence(self) -> None:
        t = ScheduledTask(name="daily check", cadence="daily", prompt="run checks")
        assert t.cadence == "daily"
        assert t.cron_expr is None
        assert t.status == TaskStatus.ACTIVE

    def test_with_cron(self) -> None:
        t = ScheduledTask(name="custom", cron_expr="*/5 * * * *", prompt="check")
        assert t.cadence is None
        assert t.cron_expr == "*/5 * * * *"

    def test_invalid_cadence(self) -> None:
        with pytest.raises(ValidationError):
            ScheduledTask(name="bad", cadence="biweekly", prompt="x")  # type: ignore[arg-type]


class TestArtifact:
    def test_creation(self) -> None:
        sid = uuid4()
        a = Artifact(
            session_id=sid,
            name="report.pdf",
            rel_path="report.pdf",
            size_bytes=1024,
            content_hash="abc123",
        )
        assert a.session_id == sid
        assert a.current_version == 1
        assert a.deleted_at is None

    def test_with_deletion(self) -> None:
        now = datetime.now(UTC)
        a = Artifact(
            session_id=uuid4(),
            name="tmp.txt",
            rel_path="tmp.txt",
            size_bytes=100,
            content_hash="def456",
            deleted_at=now,
        )
        assert a.deleted_at == now


class TestArtifactVersion:
    def test_creation(self) -> None:
        aid = uuid4()
        v = ArtifactVersion(
            artifact_id=aid,
            version=2,
            stored_rel_path="artifacts/report__v2_abc12345.pdf",
            content_hash="sha256hash",
            size_bytes=2048,
        )
        assert v.artifact_id == aid
        assert v.version == 2


class TestPermissionRecord:
    def test_grant(self) -> None:
        r = PermissionRecord(
            session_id=uuid4(),
            tool_name="Read",
            decision=PermissionDecision.GRANT,
            reason="tool in effective allowlist",
            input={"path": "/some/file"},
        )
        assert r.decision == PermissionDecision.GRANT
        assert r.consumed_by_session_id is None

    def test_deleted_observed(self) -> None:
        r = PermissionRecord(
            session_id=uuid4(),
            tool_name="fs_delete",
            decision=PermissionDecision.DELETED_OBSERVED,
            reason="watcher observed deletion",
            input={"path": "/some/file.txt"},
        )
        assert r.decision == PermissionDecision.DELETED_OBSERVED


class TestConnector:
    def test_defaults(self) -> None:
        c = Connector(name="github", command="npx", args=["-y", "@github/mcp"])
        assert c.env == {}
        assert c.tool_names == []
        assert c.requires_oauth is False
        assert c.oauth_pre_auth_done is False
        assert c.status == ConnectorStatus.REGISTERED

    def test_with_oauth(self) -> None:
        c = Connector(
            name="slack",
            command="npx",
            args=["-y", "@slack/mcp"],
            requires_oauth=True,
        )
        assert c.requires_oauth is True
        assert c.oauth_pre_auth_done is False


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings()
        assert s.server_port == 8765
        assert s.scheduler_tick_seconds == 15
        assert s.spawn_health_timeout_seconds == 30
        assert s.runner_no_event_timeout_minutes == 10
        assert s.memory_enabled is True
        assert s.scheduler_max_consecutive_failures == 5
        assert s.last_boot_at is None
        assert s.log_level == "INFO"
        assert s.claude_version_pin is None


class TestEffectivePolicy:
    def test_allow(self) -> None:
        p = EffectivePolicy(allowed={"Read", "Write"}, denied={"Bash"})
        assert p.decide("Read") == PermissionDecision.GRANT

    def test_deny_explicit(self) -> None:
        p = EffectivePolicy(allowed={"Read", "Write"}, denied={"Bash"})
        assert p.decide("Bash") == PermissionDecision.DENY

    def test_deny_unlisted(self) -> None:
        p = EffectivePolicy(allowed={"Read"}, denied=set())
        assert p.decide("Write") == PermissionDecision.DENY

    def test_denied_wins_over_allowed(self) -> None:
        p = EffectivePolicy(allowed={"WebFetch"}, denied={"WebFetch"})
        assert p.decide("WebFetch") == PermissionDecision.DENY


class TestStreamJsonEvent:
    def test_creation(self) -> None:
        ev = StreamJsonEvent(type="system", payload={"session_id": "abc"})
        assert ev.type == "system"
        assert ev.raw is None


class TestUserMessage:
    def test_defaults(self) -> None:
        m = UserMessage(message={"role": "user", "content": [{"type": "text", "text": "hello"}]})
        assert m.type == "user"
        assert m.uuid is not None
        assert m.session_id is None


class TestSessionCreate:
    def test_minimal(self) -> None:
        sc = SessionCreate(prompt="build something")
        assert sc.prompt == "build something"
        assert sc.folder_grants == []
        assert sc.allowed_tools == []
        assert sc.denied_tools == []


class TestSessionSummary:
    def test_creation(self) -> None:
        now = datetime.now(UTC)
        ss = SessionSummary(
            id=uuid4(),
            status=SessionStatus.DONE,
            title="Test",
            created_at=now,
            updated_at=now,
        )
        assert ss.artifact_count == 0
        assert ss.num_turns is None


class TestSpawnSpec:
    def test_creation(self) -> None:
        spec = SpawnSpec(
            session_id=uuid4(),
            prompt="test",
            cwd=Path("/tmp"),
            allowed_tools=["Read"],
            denied_tools=["Bash"],
        )
        assert spec.permission_mode == "manual"
        assert spec.strict_mcp_config is False


class TestMemorySnapshot:
    def test_creation(self) -> None:
        now = datetime.now(UTC)
        ms = MemorySnapshot(content="# Memory", size_bytes=8, modified_at=now)
        assert ms.content == "# Memory"
        assert ms.size_bytes == 8
