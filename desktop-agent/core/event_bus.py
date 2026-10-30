"""Tiny in-process pub/sub.

Everything interesting that happens (command parsed, refused, executed) is
published here. Phase 2 (voice UI), Phase 4 (WebSocket status feed) and Phase 6
(activity screen on the phone) all subscribe to this bus instead of the modules
calling each other directly. It is deliberately trivial: no threads, no queues,
no dependencies.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from utils.logger import get_logger

log = get_logger("events")

Handler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._wildcard: list[Handler] = []

    def subscribe(self, topic: str, handler: Handler) -> None:
        if topic == "*":
            self._wildcard.append(handler)
        else:
            self._handlers[topic].append(handler)

    def publish(self, topic: str, **payload: Any) -> Event:
        event = Event(topic=topic, payload=payload)
        for handler in (*self._handlers.get(topic, ()), *self._wildcard):
            try:
                handler(event)
            except Exception as exc:  # a bad subscriber must never break a command
                log.warning("event handler failed for %s: %s", topic, exc)
        return event
