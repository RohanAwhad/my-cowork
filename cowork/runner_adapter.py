"""RunnerAdapter — sole kernel abstraction over the Claude CLI subprocess (05 §1.3)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

from loguru import logger

from cowork.config import policy_path
from cowork.models import (
    ProcessIdentity,
    SessionEventType,
    SpawnSpec,
    StreamJsonEvent,
    UserMessage,
)


def resolve_claude_binary() -> Path:
    """Resolve claude binary: ~/.claude/local/claude first, then PATH (02 §3)."""
    local = Path.home() / ".claude" / "local" / "claude"
    if local.is_file():
        return local

    on_path = shutil.which("claude")
    if on_path is not None:
        return Path(on_path)

    raise RuntimeError(
        "claude binary not found: checked ~/.claude/local/claude and PATH"
    )


def _get_process_start_time(pid: int) -> float:
    """Get process start time on macOS via `ps`."""
    raw = subprocess.check_output(
        ["ps", "-p", str(pid), "-o", "lstart="],
        text=True,
    ).strip()
    import time

    st = time.mktime(time.strptime(raw))
    return st


def _build_args(spec: SpawnSpec) -> list[str]:
    """Assemble CLI args from SpawnSpec per 02 §2 binding template."""
    args: list[str] = [
        "-p",
        "--verbose",
        "--output-format", "stream-json",
        "--input-format", "stream-json",
        "--permission-mode", spec.permission_mode,
    ]

    if spec.allowed_tools:
        args.extend(["--allowedTools", ",".join(spec.allowed_tools)])

    if spec.denied_tools:
        args.extend(["--disallowedTools", ",".join(spec.denied_tools)])

    for d in spec.add_dirs:
        args.extend(["--add-dir", str(d)])

    if spec.mcp_config_path is not None:
        args.extend(["--mcp-config", str(spec.mcp_config_path)])
        if spec.strict_mcp_config:
            args.append("--strict-mcp-config")

    if spec.append_system_prompt is not None:
        args.extend(["--append-system-prompt", spec.append_system_prompt])

    return args


def _build_env(spec: SpawnSpec) -> dict[str, str]:
    """Build subprocess environment from spec."""
    env = dict(os.environ)
    env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
    env["MCP_TOOL_TIMEOUT"] = "30000"
    env["COWORK_SESSION_ID"] = str(spec.session_id)
    env["COWORK_POLICY_FILE"] = str(policy_path(str(spec.session_id)))
    env.update(spec.env)
    return env


def _classify_event(parsed: dict[str, object]) -> SessionEventType:
    """Map a parsed stream-json object to SessionEventType per 05 §2.2."""
    etype = parsed.get("type", "")

    if etype == "system":
        subtype = parsed.get("subtype", "")
        if subtype == "init":
            return SessionEventType.INIT
        if subtype == "init_status":
            return SessionEventType.INIT_STATUS
        return SessionEventType.MESSAGE

    if etype == "assistant":
        content = parsed.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    return SessionEventType.TOOL_USE
        return SessionEventType.MESSAGE

    if etype == "user":
        return SessionEventType.USER

    if etype == "tool_result":
        return SessionEventType.TOOL_RESULT

    if etype == "result":
        return SessionEventType.RESULT

    if etype == "error":
        return SessionEventType.ERROR

    if etype in ("exit", "close"):
        return SessionEventType.CLOSE

    return SessionEventType.RAW


def _parse_stream_line(line: str) -> StreamJsonEvent:
    """Parse a single NDJSON line from stdout into a StreamJsonEvent."""
    parsed = json.loads(line)

    if not isinstance(parsed, dict):
        return StreamJsonEvent(type="raw", raw=line)

    inner = parsed
    if parsed.get("type") == "stream_event" and "event" in parsed:
        inner = parsed["event"]
        if not isinstance(inner, dict):
            return StreamJsonEvent(type="raw", raw=line)

    event_type = _classify_event(inner)
    session_id = inner.get("session_id")
    if isinstance(session_id, str):
        pass
    else:
        session_id = None

    payload: dict[str, object] = {}
    for k, v in inner.items():
        if k not in ("type", "session_id"):
            payload[k] = v

    return StreamJsonEvent(
        type=event_type.value,
        session_id=session_id,
        payload=payload,
        raw=line,
    )


def probe(identity: ProcessIdentity) -> bool:
    """Check if process is alive AND start_time_epoch matches (02 §7 PID-reuse guard)."""
    try:
        os.kill(identity.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass

    try:
        actual_start = _get_process_start_time(identity.pid)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return False

    return abs(actual_start - identity.start_time_epoch) < 2.0


def process_group_kill(identity: ProcessIdentity, signal_num: int) -> None:
    """Send signal to process group, validating identity first (PID-reuse guard)."""
    if not probe(identity):
        logger.debug("process_group_kill: PID {} identity mismatch or dead, skipping", identity.pid)
        return

    try:
        os.killpg(identity.pid, signal_num)
    except ProcessLookupError:
        logger.debug("process_group_kill: process group {} already dead", identity.pid)


class RunnerHandle:
    """Handle to a spawned Claude CLI subprocess."""

    def __init__(self, process: asyncio.subprocess.Process, identity: ProcessIdentity) -> None:
        self._process = process
        self._identity = identity

    @property
    def pid(self) -> int:
        assert self._process.pid is not None
        return self._process.pid

    @property
    def identity(self) -> ProcessIdentity:
        return self._identity

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    async def send(self, msg: UserMessage) -> None:
        """Write NDJSON line to stdin (05 §3.1)."""
        assert self._process.stdin is not None
        line = msg.model_dump_json() + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()
        logger.debug("sent message to runner stdin: uuid={}", msg.uuid)

    async def close_input(self) -> None:
        """Close stdin (EOF) — first step of teardown."""
        if self._process.stdin is not None and not self._process.stdin.is_closing():
            self._process.stdin.close()
            await self._process.stdin.wait_closed()
            logger.debug("runner stdin closed (EOF)")

    async def stop(self) -> None:
        """Full teardown: close stdin -> wait 5s -> SIGTERM group -> wait 3s -> SIGKILL group (05 §3.3)."""
        await self.close_input()

        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
            logger.debug("runner exited cleanly after stdin EOF, rc={}", self._process.returncode)
            return
        except TimeoutError:
            pass

        logger.debug("runner did not exit after 5s, sending SIGTERM to process group {}", self.pid)
        try:
            os.killpg(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(self._process.wait(), timeout=3.0)
            logger.debug("runner exited after SIGTERM, rc={}", self._process.returncode)
            return
        except TimeoutError:
            pass

        logger.debug("runner did not exit after SIGTERM+3s, sending SIGKILL to process group {}", self.pid)
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            return

        await self._process.wait()
        logger.debug("runner killed, rc={}", self._process.returncode)

    async def events(self) -> AsyncIterator[StreamJsonEvent]:
        """Read stdout line by line, parse NDJSON, yield StreamJsonEvent (05 §2.2)."""
        assert self._process.stdout is not None
        while True:
            raw_line = await self._process.stdout.readline()
            if not raw_line:
                break
            line = raw_line.decode().rstrip("\n")
            if not line:
                continue
            try:
                event = _parse_stream_line(line)
            except (json.JSONDecodeError, Exception):
                event = StreamJsonEvent(type=SessionEventType.RAW.value, raw=line)
            yield event

    async def stderr(self) -> AsyncIterator[str]:
        """Read stderr line by line."""
        assert self._process.stderr is not None
        while True:
            raw_line = await self._process.stderr.readline()
            if not raw_line:
                break
            yield raw_line.decode().rstrip("\n")


async def spawn(spec: SpawnSpec) -> RunnerHandle:
    """Create asyncio subprocess with start_new_session=True for process groups (05 §1.3)."""
    binary = resolve_claude_binary()
    args = _build_args(spec)
    env = _build_env(spec)

    cmd = [str(binary)] + args

    logger.info("spawning runner: cmd={}, cwd={}", " ".join(cmd), spec.cwd)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(spec.cwd),
        env=env,
        start_new_session=True,
    )

    assert process.pid is not None
    start_time = _get_process_start_time(process.pid)
    identity = ProcessIdentity(pid=process.pid, start_time_epoch=start_time)

    logger.info("runner spawned: pid={}, start_time={}", process.pid, start_time)
    return RunnerHandle(process, identity)
