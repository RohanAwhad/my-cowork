"""Tests for EventBus — pub-sub, isolation, auto-detach."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from cowork.event_bus import EventBus, Topic


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


async def test_publish_subscribe(bus: EventBus) -> None:
    received: list[dict[str, Any]] = []

    async def handler(payload: dict[str, Any]) -> None:
        received.append(payload)

    bus.subscribe(Topic.SESSION, handler)
    bus.publish(Topic.SESSION, {"event": "session.started", "id": "abc"})
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0]["event"] == "session.started"


async def test_multiple_subscribers(bus: EventBus) -> None:
    received_a: list[dict[str, Any]] = []
    received_b: list[dict[str, Any]] = []

    async def handler_a(payload: dict[str, Any]) -> None:
        received_a.append(payload)

    async def handler_b(payload: dict[str, Any]) -> None:
        received_b.append(payload)

    bus.subscribe(Topic.ARTIFACT, handler_a)
    bus.subscribe(Topic.ARTIFACT, handler_b)
    bus.publish(Topic.ARTIFACT, {"name": "test.html"})
    await asyncio.sleep(0.05)

    assert len(received_a) == 1
    assert len(received_b) == 1
    assert received_a[0] == received_b[0]


async def test_subscriber_isolation(bus: EventBus) -> None:
    """A raising handler must not prevent other handlers from receiving."""
    received: list[dict[str, Any]] = []

    async def bad_handler(payload: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    async def good_handler(payload: dict[str, Any]) -> None:
        received.append(payload)

    bus.subscribe(Topic.SESSION, bad_handler)
    bus.subscribe(Topic.SESSION, good_handler)
    bus.publish(Topic.SESSION, {"val": 1})
    await asyncio.sleep(0.05)

    assert len(received) == 1


async def test_raising_handler_detached_after_3_failures(bus: EventBus) -> None:
    call_count = 0

    async def bad_handler(payload: dict[str, Any]) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("fail")

    bus.subscribe(Topic.PERMISSION, bad_handler)

    for i in range(5):
        bus.publish(Topic.PERMISSION, {"i": i})
        await asyncio.sleep(0.05)

    assert call_count == 3


async def test_unsubscribe(bus: EventBus) -> None:
    received: list[dict[str, Any]] = []

    async def handler(payload: dict[str, Any]) -> None:
        received.append(payload)

    sub = bus.subscribe(Topic.SCHEDULER, handler)
    bus.publish(Topic.SCHEDULER, {"a": 1})
    await asyncio.sleep(0.05)
    assert len(received) == 1

    bus.unsubscribe(sub)
    bus.publish(Topic.SCHEDULER, {"a": 2})
    await asyncio.sleep(0.05)
    assert len(received) == 1


async def test_different_topics_isolated(bus: EventBus) -> None:
    session_events: list[dict[str, Any]] = []
    artifact_events: list[dict[str, Any]] = []

    async def session_handler(payload: dict[str, Any]) -> None:
        session_events.append(payload)

    async def artifact_handler(payload: dict[str, Any]) -> None:
        artifact_events.append(payload)

    bus.subscribe(Topic.SESSION, session_handler)
    bus.subscribe(Topic.ARTIFACT, artifact_handler)

    bus.publish(Topic.SESSION, {"type": "session"})
    bus.publish(Topic.ARTIFACT, {"type": "artifact"})
    await asyncio.sleep(0.05)

    assert len(session_events) == 1
    assert len(artifact_events) == 1
    assert session_events[0]["type"] == "session"
    assert artifact_events[0]["type"] == "artifact"


async def test_failure_counter_resets_on_success(bus: EventBus) -> None:
    """A successful call between failures resets the failure counter."""
    call_count = 0
    should_fail = True

    async def flaky_handler(payload: dict[str, Any]) -> None:
        nonlocal call_count
        call_count += 1
        if should_fail:
            raise RuntimeError("flaky")

    bus.subscribe(Topic.CONNECTOR, flaky_handler)

    bus.publish(Topic.CONNECTOR, {"i": 0})
    await asyncio.sleep(0.05)
    bus.publish(Topic.CONNECTOR, {"i": 1})
    await asyncio.sleep(0.05)
    assert call_count == 2

    should_fail = False
    bus.publish(Topic.CONNECTOR, {"i": 2})
    await asyncio.sleep(0.05)
    assert call_count == 3

    should_fail = True
    bus.publish(Topic.CONNECTOR, {"i": 3})
    await asyncio.sleep(0.05)
    bus.publish(Topic.CONNECTOR, {"i": 4})
    await asyncio.sleep(0.05)
    assert call_count == 5
