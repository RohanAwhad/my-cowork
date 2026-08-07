"""SessionManager — lifecycle policy owner and event mapper (05 §1.2, 06 §2)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger

from cowork import config
from cowork.models import (
    EffectivePolicy,
    Session,
    SessionCreate,
    SessionEventType,
    SessionStatus,
    SessionSummary,
    SpawnSpec,
    UserMessage,
)
from cowork.runner_adapter import RunnerHandle, probe, process_group_kill, spawn
from cowork.storage import Storage

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class SessionManager:
    """Lifecycle policy owner — create/start/stop/archive sessions, event consumption, boot reconcile."""

    def __init__(
        self,
        storage: Storage,
        event_callback: EventCallback | None = None,
    ) -> None:
        self._storage = storage
        self._event_callback = event_callback
        self._handle: RunnerHandle | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._last_event_time: datetime | None = None

    async def create_session(
        self,
        create: SessionCreate,
        task_id: UUID | None = None,
    ) -> Session:
        """Create a new session — persist row, mkdir outputs dir (RE §2)."""
        from uuid import uuid4

        session_id = uuid4()
        title = create.prompt[:40].strip()
        sid_str = str(session_id)

        out_dir = config.outputs_dir(sid_str)
        sess_dir = config.session_dir(sid_str)
        sess_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        session = Session(
            id=session_id,
            status=SessionStatus.PENDING,
            title=title,
            prompt=create.prompt,
            user_selected_folders=list(create.folder_grants),
            allowed_tools=list(create.allowed_tools),
            denied_tools=list(create.denied_tools),
            outputs_dir=out_dir,
            task_id=task_id,
        )

        session = await self._storage.insert_session(session)
        logger.info("session.created id={} title={}", session_id, title)
        return session

    async def start_session(self, session_id: UUID) -> None:
        """Spawn the runner and begin event consumption (05 §1.2)."""
        session = await self._storage.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")

        if session.status not in (SessionStatus.PENDING, SessionStatus.QUEUED):
            raise ValueError(
                f"Cannot start session in status {session.status.value}"
            )

        active = await self.active_session()
        if active is not None:
            raise ValueError(
                f"One-active invariant: session {active.id} is already running"
            )

        memory_prompt: str | None = None
        add_dirs: list[Path] = []
        memory_path = config.MEMORY_PATH
        if memory_path.is_file():
            try:
                size = memory_path.stat().st_size
                if size <= config.MEMORY_SIZE_CAP_BYTES:
                    content = memory_path.read_text(encoding="utf-8")
                    memory_prompt = (
                        "The user has a persistent memory file at "
                        f"{memory_path}. Its current contents are:\n\n{content}"
                    )
                    add_dirs.append(config.DATA_ROOT)
                else:
                    logger.info(
                        "memory.md exceeds cap ({} > {}), skipping injection",
                        size,
                        config.MEMORY_SIZE_CAP_BYTES,
                    )
            except OSError:
                logger.debug("memory.md unreadable, skipping injection")

        cwd = session.user_selected_folders[0] if session.user_selected_folders else Path.cwd()
        folder_grants = list(session.user_selected_folders)

        policy = EffectivePolicy(
            allowed=set(session.allowed_tools),
            denied=set(session.denied_tools),
        )
        policy_data = policy.model_dump(mode="json")
        policy_file = config.policy_path(str(session_id))
        policy_file.parent.mkdir(parents=True, exist_ok=True)
        policy_file.write_text(json.dumps(policy_data), encoding="utf-8")

        spec = SpawnSpec(
            session_id=session_id,
            prompt=session.prompt,
            cwd=cwd,
            folder_grants=folder_grants,
            allowed_tools=session.allowed_tools,
            denied_tools=session.denied_tools,
            add_dirs=add_dirs,
            append_system_prompt=memory_prompt,
            env={
                "COWORK_SESSION_ID": str(session_id),
                "COWORK_POLICY_FILE": str(policy_file),
            },
        )

        await self._storage.transition(session_id, SessionStatus.RUNNING)

        handle = await spawn(spec)
        self._handle = handle

        await self._storage.update_session(
            session_id, process_identity=handle.identity
        )

        msg = UserMessage(
            message={"role": "user", "content": [{"type": "text", "text": session.prompt}]},
        )
        await handle.send(msg)

        self._last_event_time = datetime.now(UTC)
        self._event_task = asyncio.create_task(
            self._consume_events(session_id, handle)
        )
        self._stderr_task = asyncio.create_task(
            self._consume_stderr(handle)
        )
        self._watchdog_task = asyncio.create_task(
            self._watchdog(session_id)
        )

        logger.info("session.started id={} pid={}", session_id, handle.pid)

    async def stop_session(self, session_id: UUID) -> None:
        """Tear down the running session (05 §3.3)."""
        if self._handle is not None:
            await self._handle.stop()
            self._handle = None

        self._cancel_tasks()

        await self._storage.transition(session_id, SessionStatus.STOPPED)
        logger.info("session.stopped id={}", session_id)

    async def archive_session(self, session_id: UUID) -> None:
        """Terminal transition: done/stopped/failed → archived."""
        await self._storage.transition(session_id, SessionStatus.ARCHIVED)
        logger.info("session.archived id={}", session_id)

    async def active_session(self) -> Session | None:
        """Return the currently running session, if any."""
        summaries = await self._storage.list_sessions()
        for s in summaries:
            if s.status == SessionStatus.RUNNING:
                return await self._storage.get_session(s.id)
        return None

    async def get_session(self, session_id: UUID) -> Session | None:
        """Delegate to storage."""
        return await self._storage.get_session(session_id)

    async def list_sessions(self) -> list[SessionSummary]:
        """Delegate to storage."""
        return await self._storage.list_sessions()

    async def _consume_events(
        self, session_id: UUID, handle: RunnerHandle
    ) -> None:
        """Iterate runner events, persist and publish (05 §2.2)."""
        async for event in handle.events():
            self._last_event_time = datetime.now(UTC)
            event_type = SessionEventType(event.type)

            if event_type == SessionEventType.INIT:
                cli_session_id = event.payload.get("subtype")
                if cli_session_id is None:
                    cli_session_id = event.session_id
                if cli_session_id is not None:
                    await self._storage.update_session(
                        session_id, cli_session_id=cli_session_id
                    )

            await self._storage.append_event(
                session_id, event_type, event.payload
            )

            transcript_path = config.transcript_path(str(session_id))
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            with open(transcript_path, "a", encoding="utf-8") as f:
                f.write((event.raw or json.dumps(event.payload)) + "\n")

            if self._event_callback is not None:
                await self._event_callback(
                    "session.event",
                    {
                        "session_id": str(session_id),
                        "event_type": event_type.value,
                        "payload": event.payload,
                    },
                )

            if event_type == SessionEventType.RESULT:
                num_turns = event.payload.get("num_turns")
                is_error = event.payload.get("is_error", False)
                await self._storage.update_session(
                    session_id,
                    num_turns=num_turns,
                    is_error=is_error,
                )
                await self._storage.transition(
                    session_id, SessionStatus.DONE
                )
                self._handle = None
                logger.info(
                    "session.done id={} turns={}", session_id, num_turns
                )

            if event_type == SessionEventType.ERROR:
                error_msg = event.payload.get("error", "unknown error")
                await self._storage.update_session(
                    session_id, error=str(error_msg)
                )
                await self._storage.transition(
                    session_id, SessionStatus.FAILED
                )
                self._handle = None
                logger.error("session.failed id={} error={}", session_id, error_msg)

            if event_type == SessionEventType.CLOSE:
                exit_code = event.payload.get("exit_code")
                await self._storage.update_session(
                    session_id, exit_code=exit_code
                )
                self._handle = None

    async def _consume_stderr(self, handle: RunnerHandle) -> None:
        """Log stderr lines at debug level."""
        async for line in handle.stderr():
            logger.debug("runner stderr: {}", line)

    async def _watchdog(
        self, session_id: UUID, timeout_minutes: int = 10
    ) -> None:
        """No-event watchdog: running→failed if no events for timeout_minutes (06 §4 row 4)."""
        while True:
            await asyncio.sleep(30)
            if self._last_event_time is None:
                continue
            elapsed = (datetime.now(UTC) - self._last_event_time).total_seconds()
            if elapsed > timeout_minutes * 60:
                logger.error(
                    "watchdog timeout: no events for {} min, failing session {}",
                    timeout_minutes,
                    session_id,
                )
                session = await self._storage.get_session(session_id)
                if session is not None and session.status == SessionStatus.RUNNING:
                    await self._storage.update_session(
                        session_id,
                        error=f"no events for {timeout_minutes} min",
                    )
                    await self._storage.transition(
                        session_id, SessionStatus.FAILED
                    )
                if self._handle is not None:
                    await self._handle.stop()
                    self._handle = None
                break

    async def reconcile(self, cutoff: datetime) -> None:
        """Boot reconcile: mark stale running sessions failed, kill orphans (06 §2.1)."""
        summaries_before = await self._storage.list_sessions()
        running_before = [
            s for s in summaries_before if s.status == SessionStatus.RUNNING
        ]

        await self._storage.reconcile_running(cutoff)

        for summary in running_before:
            session = await self._storage.get_session(summary.id)
            if session is None:
                continue
            if session.process_identity is not None:
                if probe(session.process_identity):
                    import signal

                    process_group_kill(session.process_identity, signal.SIGKILL)
                    logger.info(
                        "reconcile: killed orphan process group pid={}",
                        session.process_identity.pid,
                    )

        logger.info("reconcile: marked {} stale sessions as failed", len(running_before))

    def _cancel_tasks(self) -> None:
        for task in (self._event_task, self._stderr_task, self._watchdog_task):
            if task is not None and not task.done():
                task.cancel()
        self._event_task = None
        self._stderr_task = None
        self._watchdog_task = None
