"""Tests for cowork/runner_adapter.py — mock subprocess, no real claude binary needed."""

from __future__ import annotations

import json
import signal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from cowork.models import (
    ProcessIdentity,
    SessionEventType,
    SpawnSpec,
    StreamJsonEvent,
    UserMessage,
)
from cowork.runner_adapter import (
    RunnerHandle,
    _build_args,
    _classify_event,
    _parse_stream_line,
    probe,
    process_group_kill,
    resolve_claude_binary,
    spawn,
)

# ---------------------------------------------------------------------------
# resolve_claude_binary
# ---------------------------------------------------------------------------

class TestResolveBinary:
    def test_finds_local_path(self, tmp_path: Path) -> None:
        local_bin = tmp_path / ".claude" / "local" / "claude"
        local_bin.parent.mkdir(parents=True)
        local_bin.touch()
        with patch("cowork.runner_adapter.Path.home", return_value=tmp_path):
            result = resolve_claude_binary()
        assert result == local_bin

    def test_falls_back_to_path(self, tmp_path: Path) -> None:
        with (
            patch("cowork.runner_adapter.Path.home", return_value=tmp_path),
            patch("cowork.runner_adapter.shutil.which", return_value="/usr/local/bin/claude"),
        ):
            result = resolve_claude_binary()
        assert result == Path("/usr/local/bin/claude")

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        with (
            patch("cowork.runner_adapter.Path.home", return_value=tmp_path),
            patch("cowork.runner_adapter.shutil.which", return_value=None),
        ):
            with pytest.raises(RuntimeError, match="claude binary not found"):
                resolve_claude_binary()


# ---------------------------------------------------------------------------
# _build_args
# ---------------------------------------------------------------------------

class TestBuildArgs:
    def _make_spec(self, **overrides: Any) -> SpawnSpec:
        defaults: dict[str, Any] = {
            "session_id": uuid4(),
            "prompt": "test prompt",
            "cwd": Path("/tmp/test"),
        }
        defaults.update(overrides)
        return SpawnSpec(**defaults)

    def test_base_args(self) -> None:
        spec = self._make_spec()
        args = _build_args(spec)
        assert args[:8] == [
            "-p", "--verbose",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--permission-mode", "manual",
        ]

    def test_allowed_tools_present_only_when_nonempty(self) -> None:
        spec = self._make_spec()
        args = _build_args(spec)
        assert "--allowedTools" not in args

        spec = self._make_spec(allowed_tools=["Read", "Write"])
        args = _build_args(spec)
        idx = args.index("--allowedTools")
        assert args[idx + 1] == "Read,Write"

    def test_denied_tools_present_only_when_nonempty(self) -> None:
        spec = self._make_spec()
        args = _build_args(spec)
        assert "--disallowedTools" not in args

        spec = self._make_spec(denied_tools=["Bash"])
        args = _build_args(spec)
        idx = args.index("--disallowedTools")
        assert args[idx + 1] == "Bash"

    def test_add_dirs(self) -> None:
        spec = self._make_spec(add_dirs=[Path("/home/user/project"), Path("/tmp/data")])
        args = _build_args(spec)
        pairs = [(args[i], args[i + 1]) for i in range(len(args) - 1) if args[i] == "--add-dir"]
        assert len(pairs) == 2
        assert pairs[0][1] == "/home/user/project"
        assert pairs[1][1] == "/tmp/data"

    def test_mcp_config(self) -> None:
        spec = self._make_spec(mcp_config_path=Path("/tmp/mcp.json"), strict_mcp_config=True)
        args = _build_args(spec)
        idx = args.index("--mcp-config")
        assert args[idx + 1] == "/tmp/mcp.json"
        assert "--strict-mcp-config" in args

    def test_mcp_config_no_strict(self) -> None:
        spec = self._make_spec(mcp_config_path=Path("/tmp/mcp.json"), strict_mcp_config=False)
        args = _build_args(spec)
        assert "--mcp-config" in args
        assert "--strict-mcp-config" not in args

    def test_no_mcp_config(self) -> None:
        spec = self._make_spec()
        args = _build_args(spec)
        assert "--mcp-config" not in args
        assert "--strict-mcp-config" not in args

    def test_append_system_prompt(self) -> None:
        spec = self._make_spec(append_system_prompt="You are a helpful assistant.")
        args = _build_args(spec)
        idx = args.index("--append-system-prompt")
        assert args[idx + 1] == "You are a helpful assistant."

    def test_no_append_system_prompt(self) -> None:
        spec = self._make_spec()
        args = _build_args(spec)
        assert "--append-system-prompt" not in args


# ---------------------------------------------------------------------------
# Event classification and parsing
# ---------------------------------------------------------------------------

class TestEventClassification:
    def test_system_init(self) -> None:
        assert _classify_event({"type": "system", "subtype": "init"}) == SessionEventType.INIT

    def test_system_init_status(self) -> None:
        assert _classify_event({"type": "system", "subtype": "init_status"}) == SessionEventType.INIT_STATUS

    def test_system_other(self) -> None:
        assert _classify_event({"type": "system", "subtype": "something"}) == SessionEventType.MESSAGE

    def test_assistant_text(self) -> None:
        ev: dict[str, object] = {"type": "assistant", "content": [{"type": "text", "text": "hello"}]}
        assert _classify_event(ev) == SessionEventType.MESSAGE

    def test_assistant_tool_use(self) -> None:
        ev: dict[str, object] = {"type": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "Read"}]}
        assert _classify_event(ev) == SessionEventType.TOOL_USE

    def test_user(self) -> None:
        assert _classify_event({"type": "user"}) == SessionEventType.USER

    def test_tool_result(self) -> None:
        assert _classify_event({"type": "tool_result"}) == SessionEventType.TOOL_RESULT

    def test_result(self) -> None:
        assert _classify_event({"type": "result"}) == SessionEventType.RESULT

    def test_error(self) -> None:
        assert _classify_event({"type": "error"}) == SessionEventType.ERROR

    def test_close(self) -> None:
        assert _classify_event({"type": "close"}) == SessionEventType.CLOSE
        assert _classify_event({"type": "exit"}) == SessionEventType.CLOSE

    def test_unknown(self) -> None:
        assert _classify_event({"type": "something_new"}) == SessionEventType.RAW


class TestParseStreamLine:
    def test_valid_init_event(self) -> None:
        line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc-123"})
        ev = _parse_stream_line(line)
        assert ev.type == SessionEventType.INIT.value
        assert ev.session_id == "abc-123"
        assert ev.raw == line

    def test_valid_message_event(self) -> None:
        line = json.dumps({"type": "assistant", "content": [{"type": "text", "text": "hi"}]})
        ev = _parse_stream_line(line)
        assert ev.type == SessionEventType.MESSAGE.value

    def test_valid_tool_use_event(self) -> None:
        line = json.dumps({"type": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "Read"}]})
        ev = _parse_stream_line(line)
        assert ev.type == SessionEventType.TOOL_USE.value

    def test_unwrap_stream_event_wrapper(self) -> None:
        inner = {"type": "system", "subtype": "init", "session_id": "sid-1"}
        outer = {"type": "stream_event", "event": inner}
        line = json.dumps(outer)
        ev = _parse_stream_line(line)
        assert ev.type == SessionEventType.INIT.value
        assert ev.session_id == "sid-1"

    def test_malformed_line_raises(self) -> None:
        ev = StreamJsonEvent(type=SessionEventType.RAW.value, raw="not json at all {{{")
        assert ev.type == SessionEventType.RAW.value

    def test_payload_excludes_type_and_session_id(self) -> None:
        line = json.dumps({
            "type": "result",
            "session_id": "s1",
            "num_turns": 3,
            "is_error": False,
        })
        ev = _parse_stream_line(line)
        assert "type" not in ev.payload
        assert "session_id" not in ev.payload
        assert ev.payload["num_turns"] == 3
        assert ev.payload["is_error"] is False


# ---------------------------------------------------------------------------
# RunnerHandle.stop teardown sequence
# ---------------------------------------------------------------------------

class TestRunnerHandleStop:
    @pytest.fixture
    def mock_process(self) -> MagicMock:
        proc = MagicMock()
        proc.pid = 12345
        proc.returncode = None

        stdin = MagicMock()
        stdin.is_closing = MagicMock(return_value=False)
        stdin.close = MagicMock()
        stdin.wait_closed = AsyncMock()
        proc.stdin = stdin

        return proc

    @pytest.fixture
    def handle(self, mock_process: MagicMock) -> RunnerHandle:
        identity = ProcessIdentity(pid=12345, start_time_epoch=1000.0)
        return RunnerHandle(mock_process, identity)

    async def test_clean_exit_after_eof(self, handle: RunnerHandle, mock_process: MagicMock) -> None:
        """Process exits within 5s after stdin close — no signals sent."""
        mock_process.wait = AsyncMock(return_value=0)
        mock_process.returncode = 0

        with patch("cowork.runner_adapter.os.killpg") as killpg:
            await handle.stop()
            killpg.assert_not_called()

        mock_process.stdin.close.assert_called_once()

    async def test_sigterm_after_timeout(self, handle: RunnerHandle, mock_process: MagicMock) -> None:
        """Process doesn't exit after EOF — SIGTERM sent, then clean exit."""
        call_count = 0

        async def wait_side_effect() -> int:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError()
            mock_process.returncode = -signal.SIGTERM
            return -signal.SIGTERM

        mock_process.wait = wait_side_effect

        with patch("cowork.runner_adapter.os.killpg") as killpg:
            await handle.stop()
            killpg.assert_called_once_with(12345, signal.SIGTERM)

    async def test_sigkill_as_final_fallback(self, handle: RunnerHandle, mock_process: MagicMock) -> None:
        """Process ignores SIGTERM — SIGKILL sent."""
        call_count = 0

        async def wait_side_effect() -> int:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise TimeoutError()
            mock_process.returncode = -signal.SIGKILL
            return -signal.SIGKILL

        mock_process.wait = wait_side_effect

        with patch("cowork.runner_adapter.os.killpg") as killpg:
            await handle.stop()
            assert killpg.call_count == 2
            killpg.assert_any_call(12345, signal.SIGTERM)
            killpg.assert_any_call(12345, signal.SIGKILL)


# ---------------------------------------------------------------------------
# RunnerHandle.send
# ---------------------------------------------------------------------------

class TestRunnerHandleSend:
    async def test_send_writes_ndjson(self) -> None:
        proc = MagicMock()
        proc.pid = 99
        stdin = MagicMock()
        stdin.drain = AsyncMock()
        proc.stdin = stdin

        identity = ProcessIdentity(pid=99, start_time_epoch=500.0)
        handle = RunnerHandle(proc, identity)

        msg = UserMessage(message={"role": "user", "content": [{"type": "text", "text": "hello"}]})
        await handle.send(msg)

        stdin.write.assert_called_once()
        written = stdin.write.call_args[0][0]
        parsed = json.loads(written.decode())
        assert parsed["type"] == "user"
        assert parsed["message"]["role"] == "user"


# ---------------------------------------------------------------------------
# RunnerHandle.events (async iterator)
# ---------------------------------------------------------------------------

class TestRunnerHandleEvents:
    async def test_events_parses_lines(self) -> None:
        lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}).encode() + b"\n",
            json.dumps({"type": "assistant", "content": [{"type": "text", "text": "hi"}]}).encode() + b"\n",
            b"not json\n",
            b"",
        ]

        proc = MagicMock()
        proc.pid = 42
        reader = AsyncMock()
        reader.readline = AsyncMock(side_effect=lines)
        proc.stdout = reader

        identity = ProcessIdentity(pid=42, start_time_epoch=100.0)
        handle = RunnerHandle(proc, identity)

        events: list[StreamJsonEvent] = []
        async for ev in handle.events():
            events.append(ev)

        assert len(events) == 3
        assert events[0].type == SessionEventType.INIT.value
        assert events[1].type == SessionEventType.MESSAGE.value
        assert events[2].type == SessionEventType.RAW.value
        assert events[2].raw == "not json"


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

class TestProbe:
    def test_matching_identity_returns_true(self) -> None:
        identity = ProcessIdentity(pid=123, start_time_epoch=1000.0)
        with (
            patch("cowork.runner_adapter.os.kill") as mock_kill,
            patch("cowork.runner_adapter._get_process_start_time", return_value=1000.5),
        ):
            mock_kill.return_value = None
            assert probe(identity) is True

    def test_mismatched_start_time_returns_false(self) -> None:
        identity = ProcessIdentity(pid=123, start_time_epoch=1000.0)
        with (
            patch("cowork.runner_adapter.os.kill") as mock_kill,
            patch("cowork.runner_adapter._get_process_start_time", return_value=5000.0),
        ):
            mock_kill.return_value = None
            assert probe(identity) is False

    def test_dead_process_returns_false(self) -> None:
        identity = ProcessIdentity(pid=123, start_time_epoch=1000.0)
        with patch("cowork.runner_adapter.os.kill", side_effect=ProcessLookupError):
            assert probe(identity) is False


# ---------------------------------------------------------------------------
# process_group_kill
# ---------------------------------------------------------------------------

class TestProcessGroupKill:
    def test_sends_signal_to_process_group(self) -> None:
        identity = ProcessIdentity(pid=456, start_time_epoch=2000.0)
        with (
            patch("cowork.runner_adapter.probe", return_value=True),
            patch("cowork.runner_adapter.os.killpg") as mock_killpg,
        ):
            process_group_kill(identity, signal.SIGTERM)
            mock_killpg.assert_called_once_with(456, signal.SIGTERM)

    def test_skips_when_identity_mismatch(self) -> None:
        identity = ProcessIdentity(pid=456, start_time_epoch=2000.0)
        with (
            patch("cowork.runner_adapter.probe", return_value=False),
            patch("cowork.runner_adapter.os.killpg") as mock_killpg,
        ):
            process_group_kill(identity, signal.SIGTERM)
            mock_killpg.assert_not_called()

    def test_process_lookup_error_is_nonfatal(self) -> None:
        identity = ProcessIdentity(pid=456, start_time_epoch=2000.0)
        with (
            patch("cowork.runner_adapter.probe", return_value=True),
            patch("cowork.runner_adapter.os.killpg", side_effect=ProcessLookupError),
        ):
            process_group_kill(identity, signal.SIGTERM)


# ---------------------------------------------------------------------------
# spawn
# ---------------------------------------------------------------------------

class TestSpawn:
    async def test_spawn_creates_subprocess(self, tmp_path: Path) -> None:
        spec = SpawnSpec(
            session_id=uuid4(),
            prompt="test",
            cwd=tmp_path,
            allowed_tools=["Read"],
            denied_tools=["Bash"],
            add_dirs=[tmp_path / "extra"],
            append_system_prompt="memory text",
        )

        mock_proc = MagicMock()
        mock_proc.pid = 777

        with (
            patch("cowork.runner_adapter.resolve_claude_binary", return_value=Path("/usr/bin/claude")),
            patch(
                "cowork.runner_adapter.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ) as mock_exec,
            patch("cowork.runner_adapter._get_process_start_time", return_value=3000.0),
        ):
            handle = await spawn(spec)

        assert handle.pid == 777
        assert handle.identity.pid == 777
        assert handle.identity.start_time_epoch == 3000.0

        call_args = mock_exec.call_args
        cmd_parts = list(call_args[0])
        assert cmd_parts[0] == "/usr/bin/claude"
        assert "-p" in cmd_parts
        assert "--verbose" in cmd_parts
        assert "--output-format" in cmd_parts
        assert "--allowedTools" in cmd_parts
        assert "--disallowedTools" in cmd_parts
        assert "--add-dir" in cmd_parts
        assert "--append-system-prompt" in cmd_parts

        kwargs = call_args[1]
        assert kwargs["start_new_session"] is True
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["env"]["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
        assert kwargs["env"]["MCP_TOOL_TIMEOUT"] == "30000"
        assert kwargs["env"]["COWORK_SESSION_ID"] == str(spec.session_id)
