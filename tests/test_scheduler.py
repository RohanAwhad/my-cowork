"""Tests for SchedulerEngine — cron triggers, queue drain, recovery, auto-disable."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio

from cowork.models import (
    ScheduledTask,
    Session,
    SessionCreate,
    SessionStatus,
    TaskStatus,
)
from cowork.scheduler_engine import SchedulerEngine
from cowork.storage import Storage


@pytest_asyncio.fixture
async def storage() -> AsyncIterator[Storage]:
    s = Storage(":memory:")
    await s.init()
    yield s
    await s.close()


class SessionTracker:
    """Mock session callbacks that track create/start calls."""

    def __init__(self, storage: Storage, fail_start: bool = False) -> None:
        self._storage = storage
        self._fail_start = fail_start
        self.created: list[Session] = []
        self.started: list[UUID] = []

    async def create(self, create: SessionCreate, task_id: UUID | None = None) -> Session:
        session = Session(
            prompt=create.prompt,
            allowed_tools=list(create.allowed_tools),
            denied_tools=list(create.denied_tools),
            task_id=task_id,
        )
        session = await self._storage.insert_session(session)
        self.created.append(session)
        return session

    async def start(self, session_id: UUID) -> None:
        if self._fail_start:
            raise RuntimeError("start failed")
        await self._storage.transition(session_id, SessionStatus.RUNNING)
        self.started.append(session_id)


def _make_engine(
    storage: Storage,
    tracker: SessionTracker,
    max_failures: int = 5,
    publish: object = None,
) -> SchedulerEngine:
    published: list[dict[str, object]] = []

    def _pub(topic: object, data: dict[str, object]) -> None:
        published.append(data)

    engine = SchedulerEngine(
        storage=storage,
        create_session=tracker.create,
        start_session=tracker.start,
        publish=publish or _pub,  # type: ignore[arg-type]
        tick_seconds=1,
        max_consecutive_failures=max_failures,
    )
    return engine


# -------------------------------------------------------------------
# create_task tests
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_cadence_hourly(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    now = datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC)
    task = await engine.create_task("hourly-job", "do stuff", cadence="hourly", now=now)

    assert task.cron_expr == "0 * * * *"
    assert task.cadence == "hourly"
    assert task.next_run_at is not None
    assert task.next_run_at > now
    assert task.status == TaskStatus.ACTIVE


@pytest.mark.asyncio
async def test_create_task_cadence_daily(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
    task = await engine.create_task("daily-job", "daily stuff", cadence="daily", now=now)

    assert task.cron_expr == "0 0 * * *"
    assert task.next_run_at is not None
    assert task.next_run_at.hour == 0
    assert task.next_run_at.day == 2


@pytest.mark.asyncio
async def test_create_task_cadence_weekly(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    task = await engine.create_task("weekly-job", "weekly", cadence="weekly")
    assert task.cron_expr == "0 0 * * 0"


@pytest.mark.asyncio
async def test_create_task_cadence_weekdays(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    task = await engine.create_task("weekday-job", "weekdays", cadence="weekdays")
    assert task.cron_expr == "0 0 * * 1-5"


@pytest.mark.asyncio
async def test_create_task_cadence_manual(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    task = await engine.create_task("manual-job", "manual", cadence="manual")
    assert task.cron_expr is None
    assert task.next_run_at is None
    assert task.status == TaskStatus.PAUSED


@pytest.mark.asyncio
async def test_create_task_with_cron_expr(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
    task = await engine.create_task("custom", "prompt", cron_expr="*/5 * * * *", now=now)

    assert task.cron_expr == "*/5 * * * *"
    assert task.next_run_at is not None
    assert task.next_run_at == datetime(2025, 1, 1, 10, 5, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_create_task_invalid_cron(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    with pytest.raises(ValueError, match="Invalid cron"):
        await engine.create_task("bad", "prompt", cron_expr="not a cron")


@pytest.mark.asyncio
async def test_create_task_both_cadence_and_cron(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    with pytest.raises(ValueError, match="Exactly one"):
        await engine.create_task("both", "p", cadence="hourly", cron_expr="0 * * * *")


@pytest.mark.asyncio
async def test_create_task_neither_cadence_nor_cron(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    with pytest.raises(ValueError, match="Exactly one"):
        await engine.create_task("neither", "p")


# -------------------------------------------------------------------
# tick tests
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_due_task_creates_and_starts_session(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
    task = await engine.create_task("t", "do it", cron_expr="0 * * * *", now=now - timedelta(hours=1))

    assert task.next_run_at is not None
    assert task.next_run_at <= now

    await engine.tick(now)

    assert len(tracker.created) == 1
    assert len(tracker.started) == 1
    assert tracker.created[0].task_id == task.id

    updated = await storage.get_task(task.id)
    assert updated is not None
    assert updated.next_run_at is not None
    assert updated.next_run_at > now


@pytest.mark.asyncio
async def test_tick_due_task_queued_when_slot_busy(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    running_session = Session(prompt="running", status=SessionStatus.PENDING)
    running_session = await storage.insert_session(running_session)
    await storage.transition(running_session.id, SessionStatus.RUNNING)

    now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
    await engine.create_task("t", "do it", cron_expr="0 * * * *", now=now - timedelta(hours=1))

    await engine.tick(now)

    assert len(tracker.created) == 1
    assert len(tracker.started) == 0

    session = await storage.get_session(tracker.created[0].id)
    assert session is not None
    assert session.status == SessionStatus.QUEUED


# -------------------------------------------------------------------
# queue drain tests
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_starts_queued_session_after_end(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    task = ScheduledTask(
        name="drain-t", prompt="p", cron_expr="0 * * * *",
        status=TaskStatus.ACTIVE,
        next_run_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    task = await storage.insert_task(task)

    queued_session = Session(prompt="queued", status=SessionStatus.PENDING, task_id=task.id)
    queued_session = await storage.insert_session(queued_session)
    await storage.transition(queued_session.id, SessionStatus.QUEUED)

    ended_session = Session(prompt="ended", status=SessionStatus.PENDING)
    ended_session = await storage.insert_session(ended_session)
    await storage.transition(ended_session.id, SessionStatus.RUNNING)
    await storage.transition(ended_session.id, SessionStatus.DONE)

    await engine.on_session_ended({
        "session_id": str(ended_session.id),
    })

    assert queued_session.id in tracker.started

    refreshed = await storage.get_session(queued_session.id)
    assert refreshed is not None
    assert refreshed.status == SessionStatus.RUNNING


@pytest.mark.asyncio
async def test_drain_failure_marks_session_failed(storage: Storage) -> None:
    tracker = SessionTracker(storage, fail_start=True)
    engine = _make_engine(storage, tracker)

    task = ScheduledTask(
        name="t", prompt="p", cron_expr="0 * * * *",
        status=TaskStatus.QUEUED,
        next_run_at=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
    )
    task = await storage.insert_task(task)

    queued_session = Session(prompt="queued", status=SessionStatus.PENDING, task_id=task.id)
    queued_session = await storage.insert_session(queued_session)
    await storage.transition(queued_session.id, SessionStatus.QUEUED)

    ended_session = Session(prompt="done", status=SessionStatus.PENDING)
    ended_session = await storage.insert_session(ended_session)
    await storage.transition(ended_session.id, SessionStatus.RUNNING)
    await storage.transition(ended_session.id, SessionStatus.DONE)

    await engine.on_session_ended({"session_id": str(ended_session.id)})

    refreshed_session = await storage.get_session(queued_session.id)
    assert refreshed_session is not None
    assert refreshed_session.status == SessionStatus.FAILED

    refreshed_task = await storage.get_task(task.id)
    assert refreshed_task is not None
    assert refreshed_task.status == TaskStatus.ACTIVE


# -------------------------------------------------------------------
# trigger_task (manual run-now) tests
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_task_starts_immediately(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    task = await engine.create_task("t", "prompt", cadence="manual")

    session = await engine.trigger_task(task.id)

    assert len(tracker.started) == 1
    assert tracker.started[0] == session.id

    updated_task = await storage.get_task(task.id)
    assert updated_task is not None
    assert updated_task.last_run_at is not None
    assert updated_task.last_run_session_id == session.id


@pytest.mark.asyncio
async def test_trigger_task_queues_when_busy(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    running = Session(prompt="running", status=SessionStatus.PENDING)
    running = await storage.insert_session(running)
    await storage.transition(running.id, SessionStatus.RUNNING)

    task = await engine.create_task("t", "prompt", cadence="manual")
    session = await engine.trigger_task(task.id)

    assert len(tracker.started) == 0
    refreshed = await storage.get_session(session.id)
    assert refreshed is not None
    assert refreshed.status == SessionStatus.QUEUED


# -------------------------------------------------------------------
# recover_missed tests
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_missed_replays_latest_only(storage: Storage) -> None:
    """1 day missed with hourly cron → single replay (coalescing)."""
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    last_boot = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC)

    task = ScheduledTask(
        name="missed", prompt="p", cron_expr="0 * * * *",
        status=TaskStatus.ACTIVE,
        next_run_at=datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC),
    )
    task = await storage.insert_task(task)

    await engine.recover_missed(now, last_boot)

    assert len(tracker.created) == 1
    assert tracker.created[0].task_id == task.id

    updated = await storage.get_task(task.id)
    assert updated is not None
    assert updated.next_run_at is not None
    assert updated.next_run_at > now


@pytest.mark.asyncio
async def test_recover_missed_3_days_still_one_replay(storage: Storage) -> None:
    """3 days missed with daily cron → still only one replay."""
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    last_boot = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2025, 1, 4, 0, 0, 0, tzinfo=UTC)

    task = ScheduledTask(
        name="missed3", prompt="p", cron_expr="0 0 * * *",
        status=TaskStatus.ACTIVE,
        next_run_at=datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC),
    )
    task = await storage.insert_task(task)

    await engine.recover_missed(now, last_boot)

    assert len(tracker.created) == 1

    updated = await storage.get_task(task.id)
    assert updated is not None
    assert updated.next_run_at is not None
    assert updated.next_run_at > now


@pytest.mark.asyncio
async def test_recover_missed_grid_preserving_recompute(storage: Storage) -> None:
    """Next run after recovery should be computed from latest missed time, not from now."""
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    last_boot = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2025, 1, 1, 2, 30, 0, tzinfo=UTC)

    task = ScheduledTask(
        name="grid", prompt="p", cron_expr="0 * * * *",
        status=TaskStatus.ACTIVE,
        next_run_at=datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC),
    )
    task = await storage.insert_task(task)

    await engine.recover_missed(now, last_boot)

    updated = await storage.get_task(task.id)
    assert updated is not None
    assert updated.next_run_at == datetime(2025, 1, 1, 3, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_recover_missed_no_action_when_not_in_window(storage: Storage) -> None:
    """Task whose next_run_at is after now → no recovery needed."""
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    last_boot = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2025, 1, 1, 0, 30, 0, tzinfo=UTC)

    task = ScheduledTask(
        name="future", prompt="p", cron_expr="0 * * * *",
        status=TaskStatus.ACTIVE,
        next_run_at=datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC),
    )
    task = await storage.insert_task(task)

    await engine.recover_missed(now, last_boot)

    assert len(tracker.created) == 0


# -------------------------------------------------------------------
# auto-disable tests
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_disable_after_consecutive_failures(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker, max_failures=5)

    task = ScheduledTask(
        name="failing", prompt="p", cron_expr="0 * * * *",
        status=TaskStatus.ACTIVE,
        next_run_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    task = await storage.insert_task(task)

    for i in range(5):
        session = Session(prompt="fail", status=SessionStatus.PENDING, task_id=task.id, error="boom")
        session = await storage.insert_session(session)
        await storage.transition(session.id, SessionStatus.RUNNING)
        await storage.transition(session.id, SessionStatus.FAILED)

        await engine.on_session_ended({"session_id": str(session.id)})

    updated = await storage.get_task(task.id)
    assert updated is not None
    assert updated.status == TaskStatus.DISABLED


@pytest.mark.asyncio
async def test_auto_disable_reset_on_success(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker, max_failures=5)

    task = ScheduledTask(
        name="intermittent", prompt="p", cron_expr="0 * * * *",
        status=TaskStatus.ACTIVE,
        next_run_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    task = await storage.insert_task(task)

    for _ in range(4):
        session = Session(prompt="fail", status=SessionStatus.PENDING, task_id=task.id, error="boom")
        session = await storage.insert_session(session)
        await storage.transition(session.id, SessionStatus.RUNNING)
        await storage.transition(session.id, SessionStatus.FAILED)
        await engine.on_session_ended({"session_id": str(session.id)})

    success = Session(prompt="ok", status=SessionStatus.PENDING, task_id=task.id)
    success = await storage.insert_session(success)
    await storage.transition(success.id, SessionStatus.RUNNING)
    await storage.transition(success.id, SessionStatus.DONE)
    await engine.on_session_ended({"session_id": str(success.id)})

    for _ in range(4):
        session = Session(prompt="fail", status=SessionStatus.PENDING, task_id=task.id, error="boom")
        session = await storage.insert_session(session)
        await storage.transition(session.id, SessionStatus.RUNNING)
        await storage.transition(session.id, SessionStatus.FAILED)
        await engine.on_session_ended({"session_id": str(session.id)})

    updated = await storage.get_task(task.id)
    assert updated is not None
    assert updated.status == TaskStatus.ACTIVE


# -------------------------------------------------------------------
# delete_task tests
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_task_cancels_queued_sessions(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    task = ScheduledTask(
        name="del", prompt="p", cron_expr="0 * * * *",
        status=TaskStatus.ACTIVE,
        next_run_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    task = await storage.insert_task(task)

    queued = Session(prompt="q", status=SessionStatus.PENDING, task_id=task.id)
    queued = await storage.insert_session(queued)
    await storage.transition(queued.id, SessionStatus.QUEUED)

    await engine.delete_task(task.id)

    refreshed = await storage.get_session(queued.id)
    assert refreshed is not None
    assert refreshed.status == SessionStatus.STOPPED

    updated_task = await storage.get_task(task.id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.DISABLED


# -------------------------------------------------------------------
# tick lock prevents concurrent execution
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_lock_prevents_concurrent(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    now = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
    await engine.create_task("t", "p", cron_expr="0 * * * *", now=now - timedelta(hours=1))

    await asyncio.gather(
        engine.tick(now),
        engine.tick(now),
    )

    assert len(tracker.created) == 1


# -------------------------------------------------------------------
# start/stop tick loop
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_stop_tick_loop(storage: Storage) -> None:
    tracker = SessionTracker(storage)
    engine = _make_engine(storage, tracker)

    engine.start_tick_loop()
    assert engine._tick_task is not None
    assert not engine._tick_task.done()

    engine.stop_tick_loop()
    assert engine._tick_task is None
