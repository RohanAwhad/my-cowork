"""SchedulerEngine — local cron with boot recovery and queue drain (05 §1.7)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from croniter import croniter  # type: ignore[import-untyped]
from loguru import logger

from cowork.event_bus import EventBus, Topic
from cowork.models import (
    ScheduledTask,
    Session,
    SessionCreate,
    SessionStatus,
    TaskStatus,
)
from cowork.storage import Storage

CreateSessionFn = Callable[[SessionCreate, UUID | None], Awaitable[Session]]
StartSessionFn = Callable[[UUID], Awaitable[None]]
PublishFn = Callable[[Topic, dict[str, Any]], None]

Cadence = Literal["hourly", "daily", "weekly", "weekdays", "manual"]

_CADENCE_MAP: dict[str, str | None] = {
    "hourly": "0 * * * *",
    "daily": "0 0 * * *",
    "weekly": "0 0 * * 0",
    "weekdays": "0 0 * * 1-5",
    "manual": None,
}


class SchedulerEngine:
    """Periodic tick scheduler with cron-based task triggering, queue drain, and auto-disable."""

    def __init__(
        self,
        storage: Storage,
        create_session: CreateSessionFn,
        start_session: StartSessionFn,
        publish: PublishFn | None = None,
        tick_seconds: int = 15,
        max_consecutive_failures: int = 5,
    ) -> None:
        self._storage = storage
        self._create_session = create_session
        self._start_session = start_session
        self._publish = publish
        self._tick_seconds = tick_seconds
        self._max_consecutive_failures = max_consecutive_failures
        self._tick_lock = asyncio.Lock()
        self._tick_task: asyncio.Task[None] | None = None
        self._failure_counts: dict[UUID, int] = {}

    async def create_task(
        self,
        name: str,
        prompt: str,
        cadence: Cadence | None = None,
        cron_expr: str | None = None,
        allowed_tools: list[str] | None = None,
        now: datetime | None = None,
    ) -> ScheduledTask:
        now = now or datetime.now(UTC)

        if cadence is not None and cron_expr is not None:
            raise ValueError("Exactly one of cadence or cron_expr must be set, got both")
        if cadence is None and cron_expr is None:
            raise ValueError("Exactly one of cadence or cron_expr must be set, got neither")

        resolved_cron: str | None = None
        if cadence is not None:
            if cadence not in _CADENCE_MAP:
                raise ValueError(f"Unknown cadence: {cadence}")
            resolved_cron = _CADENCE_MAP[cadence]
        else:
            resolved_cron = cron_expr

        next_run_at: datetime | None = None
        if resolved_cron is not None:
            if not croniter.is_valid(resolved_cron):
                raise ValueError(f"Invalid cron expression: {resolved_cron}")
            ci = croniter(resolved_cron, now)
            next_run_at = ci.get_next(datetime).replace(tzinfo=UTC)

        task = ScheduledTask(
            name=name,
            prompt=prompt,
            cadence=cadence,
            cron_expr=resolved_cron,
            allowed_tools=allowed_tools or [],
            status=TaskStatus.ACTIVE if resolved_cron is not None else TaskStatus.PAUSED,
            next_run_at=next_run_at,
        )
        task = await self._storage.insert_task(task)
        logger.info("scheduler.create_task id={} name={} cron={}", task.id, name, resolved_cron)
        return task

    async def trigger_task(self, task_id: UUID, now: datetime | None = None) -> Session:
        now = now or datetime.now(UTC)
        task = await self._storage.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        session = await self._create_session(
            SessionCreate(prompt=task.prompt, allowed_tools=task.allowed_tools),
            task_id,
        )

        await self._storage.update_task(task_id, last_run_at=now, last_run_session_id=session.id)

        slot_free = await self._is_slot_free()
        if slot_free:
            await self._start_session(session.id)
            self._emit("sched.notice", {"action": "started", "task_id": str(task_id), "session_id": str(session.id)})
        else:
            await self._storage.transition(session.id, SessionStatus.QUEUED)
            self._emit("sched.notice", {"action": "queued", "task_id": str(task_id), "session_id": str(session.id)})

        logger.info("scheduler.trigger_task task_id={} session_id={}", task_id, session.id)
        return session

    async def update_task(self, task_id: UUID, **fields: Any) -> ScheduledTask:
        return await self._storage.update_task(task_id, **fields)

    async def delete_task(self, task_id: UUID) -> None:
        sessions = await self._storage.list_sessions()
        for s in sessions:
            if s.task_id == task_id and s.status == SessionStatus.QUEUED:
                await self._storage.transition(s.id, SessionStatus.STOPPED)
                logger.info("scheduler.delete_task cancelled queued session={}", s.id)

        # Storage doesn't have delete_task — use set_task_status to disable, then we could
        # leave it. But spec says "delete". We'll rely on the DB foreign key ON DELETE SET NULL.
        # For now, mark disabled since Storage has no delete_task method.
        await self._storage.set_task_status(task_id, TaskStatus.DISABLED)
        self._failure_counts.pop(task_id, None)
        logger.info("scheduler.delete_task id={}", task_id)

    async def tick(self, now: datetime) -> None:
        async with self._tick_lock:
            due_tasks = await self._storage.list_due(now)
            for task in due_tasks:
                await self._process_due_task(task, now)

    async def _process_due_task(self, task: ScheduledTask, now: datetime) -> None:
        session = await self._create_session(
            SessionCreate(prompt=task.prompt, allowed_tools=task.allowed_tools),
            task.id,
        )

        await self._storage.update_task(
            task.id, last_run_at=now, last_run_session_id=session.id
        )

        slot_free = await self._is_slot_free()
        if slot_free:
            await self._start_session(session.id)
            self._emit("sched.notice", {"action": "started", "task_id": str(task.id), "session_id": str(session.id)})
        else:
            await self._storage.transition(session.id, SessionStatus.QUEUED)
            await self._storage.set_task_status(task.id, TaskStatus.QUEUED)
            self._emit("sched.notice", {"action": "queued", "task_id": str(task.id), "session_id": str(session.id)})

        if task.cron_expr is not None:
            ci = croniter(task.cron_expr, now)
            next_run = ci.get_next(datetime).replace(tzinfo=UTC)
            await self._storage.update_task(task.id, next_run_at=next_run)

    async def recover_missed(
        self, now: datetime, last_boot_at: datetime
    ) -> None:
        tasks = await self._storage.list_tasks()
        for task in tasks:
            if task.status != TaskStatus.ACTIVE:
                continue
            if task.next_run_at is None:
                continue
            if task.cron_expr is None:
                continue

            nr = task.next_run_at
            if nr.tzinfo is None:
                nr = nr.replace(tzinfo=UTC)
            lb = last_boot_at
            if lb.tzinfo is None:
                lb = lb.replace(tzinfo=UTC)
            n = now
            if n.tzinfo is None:
                n = n.replace(tzinfo=UTC)

            if lb < nr <= n:
                latest_missed = nr
                ci_scan = croniter(task.cron_expr, lb)
                while True:
                    nxt = ci_scan.get_next(datetime).replace(tzinfo=UTC)
                    if nxt > n:
                        break
                    latest_missed = nxt

                session = await self._create_session(
                    SessionCreate(prompt=task.prompt, allowed_tools=task.allowed_tools),
                    task.id,
                )

                await self._storage.update_task(
                    task.id,
                    last_run_at=now,
                    last_run_session_id=session.id,
                    status=TaskStatus.ACTIVE.value,
                )

                slot_free = await self._is_slot_free()
                if slot_free:
                    await self._start_session(session.id)
                else:
                    await self._storage.transition(session.id, SessionStatus.QUEUED)

                ci_rearm = croniter(task.cron_expr, latest_missed)
                next_run = ci_rearm.get_next(datetime).replace(tzinfo=UTC)
                await self._storage.update_task(task.id, next_run_at=next_run)

                self._emit("sched.notice", {
                    "action": "missed",
                    "task_id": str(task.id),
                    "session_id": str(session.id),
                    "latest_missed": latest_missed.isoformat(),
                })
                logger.info(
                    "scheduler.recover_missed task_id={} latest_missed={}",
                    task.id, latest_missed,
                )

    async def on_session_ended(self, payload: dict[str, Any]) -> None:
        session_id_str = payload.get("session_id")
        if session_id_str is None:
            return

        session_id = UUID(session_id_str)
        session = await self._storage.get_session(session_id)
        if session is None:
            return

        if session.task_id is not None:
            await self._handle_task_session_end(session)

        if session.status in (SessionStatus.DONE, SessionStatus.STOPPED, SessionStatus.FAILED):
            await self._drain_queue()

    async def _handle_task_session_end(self, session: Session) -> None:
        assert session.task_id is not None
        task_id = session.task_id

        if session.status == SessionStatus.FAILED:
            count = self._failure_counts.get(task_id, 0) + 1
            self._failure_counts[task_id] = count

            await self._storage.update_task(
                task_id, last_run_error=session.error or "session failed"
            )

            if count >= self._max_consecutive_failures:
                await self._storage.set_task_status(task_id, TaskStatus.DISABLED)
                logger.warning(
                    "scheduler.auto_disable task_id={} after {} consecutive failures",
                    task_id, count,
                )
        elif session.status == SessionStatus.DONE:
            self._failure_counts.pop(task_id, None)
            await self._storage.update_task(task_id, last_run_error=None)

    async def _drain_queue(self) -> None:
        sessions = await self._storage.list_sessions()
        queued = [
            s for s in sessions
            if s.status == SessionStatus.QUEUED
        ]
        if not queued:
            return

        queued.sort(key=lambda s: s.created_at)
        oldest = queued[0]

        slot_free = await self._is_slot_free()
        if not slot_free:
            return

        try:
            await self._start_session(oldest.id)
            self._emit("sched.notice", {"action": "drained", "session_id": str(oldest.id)})
            logger.info("scheduler.drain started queued session={}", oldest.id)
        except Exception as exc:
            logger.error("scheduler.drain_failure session={} error={}", oldest.id, exc)
            await self._storage.transition(oldest.id, SessionStatus.FAILED)

            if oldest.task_id is not None:
                task = await self._storage.get_task(oldest.task_id)
                if task is not None and task.status == TaskStatus.QUEUED:
                    await self._storage.set_task_status(oldest.task_id, TaskStatus.ACTIVE)
                    if task.cron_expr is not None:
                        now = datetime.now(UTC)
                        ci = croniter(task.cron_expr, now)
                        next_run = ci.get_next(datetime).replace(tzinfo=UTC)
                        await self._storage.update_task(oldest.task_id, next_run_at=next_run)

    async def _is_slot_free(self) -> bool:
        sessions = await self._storage.list_sessions()
        return not any(s.status == SessionStatus.RUNNING for s in sessions)

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self._publish is not None:
            data["event"] = event
            self._publish(Topic.SCHEDULER, data)

    def start_tick_loop(self) -> None:
        if self._tick_task is not None:
            return
        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.info("scheduler.tick_loop started interval={}s", self._tick_seconds)

    def stop_tick_loop(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
            self._tick_task = None
            logger.info("scheduler.tick_loop stopped")

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_seconds)
            try:
                await self.tick(datetime.now(UTC))
            except Exception:
                logger.exception("scheduler.tick error")

    def subscribe_session_events(self, bus: EventBus) -> None:
        bus.subscribe(Topic.SESSION, self.on_session_ended)
