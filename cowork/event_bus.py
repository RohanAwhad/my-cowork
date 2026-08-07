"""EventBus — in-process asyncio pub-sub (05 §1.5, 03 §3)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from loguru import logger


class Topic(StrEnum):
    SESSION = "session"
    ARTIFACT = "artifact"
    PERMISSION = "permission"
    SCHEDULER = "scheduler"
    CONNECTOR = "connector"


@dataclass
class Subscription:
    topic: Topic
    handler: Callable[[dict[str, Any]], Awaitable[None]]
    _id: int = field(default=0)
    _failure_count: int = field(default=0, repr=False)
    _detached: bool = field(default=False, repr=False)

    MAX_CONSECUTIVE_FAILURES: int = field(default=3, init=False, repr=False)


class EventBus:
    """Fan-out pub-sub: publish never raises to the publisher; handlers run in isolated tasks."""

    def __init__(self) -> None:
        self._subs: dict[Topic, list[Subscription]] = defaultdict(list)
        self._next_id = 0

    def subscribe(
        self, topic: Topic, handler: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> Subscription:
        self._next_id += 1
        sub = Subscription(topic=topic, handler=handler, _id=self._next_id)
        self._subs[topic].append(sub)
        logger.debug("event_bus.subscribe topic={} sub_id={}", topic, sub._id)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        subs = self._subs.get(sub.topic, [])
        self._subs[sub.topic] = [s for s in subs if s._id != sub._id]
        sub._detached = True
        logger.debug("event_bus.unsubscribe topic={} sub_id={}", sub.topic, sub._id)

    def publish(self, topic: Topic, payload: dict[str, Any]) -> None:
        subs = list(self._subs.get(topic, []))
        for sub in subs:
            if sub._detached:
                continue
            asyncio.create_task(self._dispatch(sub, payload))

    async def _dispatch(self, sub: Subscription, payload: dict[str, Any]) -> None:
        if sub._detached:
            return
        try:
            await sub.handler(payload)
            sub._failure_count = 0
        except Exception:
            sub._failure_count += 1
            logger.warning(
                "event_bus: handler failed ({}/{}) topic={} sub_id={}",
                sub._failure_count,
                sub.MAX_CONSECUTIVE_FAILURES,
                sub.topic,
                sub._id,
            )
            if sub._failure_count >= sub.MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "event_bus: detaching handler after {} consecutive failures, topic={} sub_id={}",
                    sub.MAX_CONSECUTIVE_FAILURES,
                    sub.topic,
                    sub._id,
                )
                self.unsubscribe(sub)
