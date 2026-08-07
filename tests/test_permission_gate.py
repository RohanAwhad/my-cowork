"""Tests for PermissionGate — spawn-time policy enforcement, grant validation, audit."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from cowork import config
from cowork.models import (
    EffectivePolicy,
    PermissionDecision,
    Session,
)
from cowork.permission_gate import (
    consume_approve_future,
    decide,
    generate_policy_file,
    ingest_hook_decisions,
    record,
    resolve_policy,
    validate_grant,
)
from cowork.storage import Storage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def storage() -> AsyncIterator[Storage]:
    s = Storage(":memory:")
    await s.init()
    yield s
    await s.close()


@pytest.fixture
def session_id() -> UUID:
    return uuid4()


# ---------------------------------------------------------------------------
# resolve_policy tests
# ---------------------------------------------------------------------------


class TestResolvePolicy:
    def test_union_of_allowed(self) -> None:
        session = Session(prompt="test", allowed_tools=["Read", "Write", "Edit"])
        policy = resolve_policy(session)
        assert policy.allowed == {"Read", "Write", "Edit"}
        assert policy.denied == set()

    def test_denied_wins(self) -> None:
        session = Session(
            prompt="test",
            allowed_tools=["Read", "Write", "WebFetch"],
            denied_tools=["WebFetch", "Bash"],
        )
        policy = resolve_policy(session)
        assert "WebFetch" not in policy.allowed
        assert "WebFetch" in policy.denied
        assert "Bash" in policy.denied
        assert policy.allowed == {"Read", "Write"}

    def test_empty_tools(self) -> None:
        session = Session(prompt="test")
        policy = resolve_policy(session)
        assert policy.allowed == set()
        assert policy.denied == set()

    def test_all_denied(self) -> None:
        session = Session(
            prompt="test",
            allowed_tools=["Read"],
            denied_tools=["Read"],
        )
        policy = resolve_policy(session)
        assert policy.allowed == set()
        assert "Read" in policy.denied


# ---------------------------------------------------------------------------
# decide tests
# ---------------------------------------------------------------------------


class TestDecide:
    def test_grant_for_allowed(self) -> None:
        policy = EffectivePolicy(allowed={"Read", "Write"}, denied={"Bash"})
        assert decide("Read", policy) == PermissionDecision.GRANT

    def test_deny_for_denied(self) -> None:
        policy = EffectivePolicy(allowed={"Read"}, denied={"Bash"})
        assert decide("Bash", policy) == PermissionDecision.DENY

    def test_deny_for_unlisted(self) -> None:
        policy = EffectivePolicy(allowed={"Read"}, denied={"Bash"})
        assert decide("WebFetch", policy) == PermissionDecision.DENY

    def test_deny_is_default(self) -> None:
        policy = EffectivePolicy()
        assert decide("anything", policy) == PermissionDecision.DENY


# ---------------------------------------------------------------------------
# validate_grant tests
# ---------------------------------------------------------------------------


class TestValidateGrant:
    def test_accept_valid_absolute_under_home(self) -> None:
        home = Path.home()
        valid = home / "projects" / "myapp"
        validate_grant(valid)

    def test_reject_relative_path(self) -> None:
        with pytest.raises(ValueError, match="absolute"):
            validate_grant(Path("relative/path"))

    def test_reject_home_itself(self) -> None:
        with pytest.raises(ValueError, match="HOME itself"):
            validate_grant(Path.home())

    def test_reject_outside_home(self) -> None:
        with pytest.raises(ValueError, match="under \\$HOME"):
            validate_grant(Path("/tmp/outside"))

    def test_reject_co_work_db(self) -> None:
        with pytest.raises(ValueError, match="app-owned"):
            validate_grant(config.DATA_ROOT / "cowork.db")

    def test_reject_co_work_sessions(self) -> None:
        with pytest.raises(ValueError, match="app-owned"):
            validate_grant(config.DATA_ROOT / "sessions")

    def test_accept_memory_md(self) -> None:
        validate_grant(config.MEMORY_PATH)

    def test_reject_data_root_itself(self) -> None:
        with pytest.raises(ValueError, match="app-owned"):
            validate_grant(config.DATA_ROOT)


# ---------------------------------------------------------------------------
# generate_policy_file tests
# ---------------------------------------------------------------------------


class TestGeneratePolicyFile:
    def test_correct_format(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sid = uuid4()
        policy = EffectivePolicy(allowed={"Read", "Write"}, denied={"Bash"})

        policy_dir = tmp_path / "sessions" / str(sid)
        monkeypatch.setattr(
            config, "policy_path", lambda s: policy_dir / "policy.json"
        )

        result = generate_policy_file(sid, policy)
        assert result.exists()

        data = json.loads(result.read_text())
        assert data["sessionId"] == str(sid)
        assert sorted(data["allowed"]) == ["Read", "Write"]
        assert data["denied"] == ["Bash"]

    def test_permissions_0600(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sid = uuid4()
        policy = EffectivePolicy(allowed={"Read"})

        policy_dir = tmp_path / "sessions" / str(sid)
        monkeypatch.setattr(
            config, "policy_path", lambda s: policy_dir / "policy.json"
        )

        result = generate_policy_file(sid, policy)
        mode = result.stat().st_mode
        assert mode & 0o777 == 0o600


# ---------------------------------------------------------------------------
# record tests
# ---------------------------------------------------------------------------


class TestRecord:
    @pytest.mark.asyncio
    async def test_db_insert(self, storage: Storage, session_id: UUID) -> None:
        session = Session(id=session_id, prompt="test", outputs_dir=Path("/tmp/out"))
        await storage.insert_session(session)

        rec = await record(
            storage=storage,
            session_id=session_id,
            task_id=None,
            tool_name="Read",
            decision=PermissionDecision.GRANT,
            reason="allowed by policy",
            input_data={"path": "/some/file"},
        )

        assert rec.tool_name == "Read"
        assert rec.decision == PermissionDecision.GRANT

        records = await storage.list_permissions(session_id)
        assert len(records) == 1
        assert records[0].tool_name == "Read"

    @pytest.mark.asyncio
    async def test_audit_jsonl_mirror(
        self, storage: Storage, session_id: UUID, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = Session(id=session_id, prompt="test", outputs_dir=Path("/tmp/out"))
        await storage.insert_session(session)

        audit_file = tmp_path / str(session_id) / "audit.jsonl"
        monkeypatch.setattr(config, "audit_path", lambda s: audit_file)

        await record(
            storage=storage,
            session_id=session_id,
            task_id=None,
            tool_name="Write",
            decision=PermissionDecision.DENY,
            reason="not in allowlist",
            input_data={},
        )

        assert audit_file.exists()
        lines = audit_file.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["tool_name"] == "Write"
        assert data["decision"] == "deny"


# ---------------------------------------------------------------------------
# consume_approve_future tests
# ---------------------------------------------------------------------------


class TestConsumeApproveFuture:
    @pytest.mark.asyncio
    async def test_finds_and_consumes(self, storage: Storage) -> None:
        sid = uuid4()
        session = Session(id=sid, prompt="test", outputs_dir=Path("/tmp/out"))
        await storage.insert_session(session)

        await storage.append_permission(
            session_id=sid,
            task_id=None,
            tool_name="WebFetch",
            decision=PermissionDecision.APPROVE_FUTURE,
            reason="user approved",
            input_data={},
        )

        consuming_sid = uuid4()
        consuming_session = Session(id=consuming_sid, prompt="test2", outputs_dir=Path("/tmp/out2"))
        await storage.insert_session(consuming_session)

        result = await consume_approve_future(storage, sid, "WebFetch")
        assert result is not None
        assert result.tool_name == "WebFetch"
        assert result.consumed_by_session_id == consuming_sid or result.consumed_by_session_id == sid

    @pytest.mark.asyncio
    async def test_skips_scheduled_sessions(self, storage: Storage) -> None:
        sid = uuid4()
        task_id = uuid4()
        session = Session(id=sid, prompt="test", outputs_dir=Path("/tmp/out"))
        await storage.insert_session(session)

        from cowork.models import ScheduledTask

        task = ScheduledTask(id=task_id, name="test-task", prompt="test", cron_expr="0 * * * *")
        await storage.insert_task(task)

        await storage.append_permission(
            session_id=sid,
            task_id=task_id,
            tool_name="WebFetch",
            decision=PermissionDecision.APPROVE_FUTURE,
            reason="user approved",
            input_data={},
        )

        result = await consume_approve_future(storage, sid, "WebFetch")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, storage: Storage) -> None:
        sid = uuid4()
        session = Session(id=sid, prompt="test", outputs_dir=Path("/tmp/out"))
        await storage.insert_session(session)

        result = await consume_approve_future(storage, sid, "NonexistentTool")
        assert result is None


# ---------------------------------------------------------------------------
# ingest_hook_decisions tests
# ---------------------------------------------------------------------------


class TestIngestHookDecisions:
    @pytest.mark.asyncio
    async def test_parses_lines(
        self, storage: Storage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = uuid4()
        session = Session(id=sid, prompt="test", outputs_dir=Path("/tmp/out"))
        await storage.insert_session(session)

        hook_file = tmp_path / "hook-decisions.jsonl"
        hook_file.write_text(
            json.dumps({"tool_name": "Read", "decision": "grant", "reason": "hook allowed", "input": {"path": "/x"}})
            + "\n"
            + json.dumps({"tool_name": "Write", "decision": "deny", "reason": "hook denied", "input": {}})
            + "\n"
        )
        monkeypatch.setattr(config, "hook_decisions_path", lambda s: hook_file)

        await ingest_hook_decisions(storage, sid)

        records = await storage.list_permissions(sid)
        assert len(records) == 2
        names = {r.tool_name for r in records}
        assert names == {"Read", "Write"}

    @pytest.mark.asyncio
    async def test_skips_bad_lines(
        self, storage: Storage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = uuid4()
        session = Session(id=sid, prompt="test", outputs_dir=Path("/tmp/out"))
        await storage.insert_session(session)

        hook_file = tmp_path / "hook-decisions.jsonl"
        hook_file.write_text(
            "not valid json\n"
            + json.dumps({"tool_name": "Read", "decision": "grant", "reason": "ok", "input": {}})
            + "\n"
        )
        monkeypatch.setattr(config, "hook_decisions_path", lambda s: hook_file)

        await ingest_hook_decisions(storage, sid)

        records = await storage.list_permissions(sid)
        assert len(records) == 1
        assert records[0].tool_name == "Read"

    @pytest.mark.asyncio
    async def test_missing_file(
        self, storage: Storage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = uuid4()
        monkeypatch.setattr(
            config, "hook_decisions_path", lambda s: tmp_path / "nonexistent.jsonl"
        )
        await ingest_hook_decisions(storage, sid)
