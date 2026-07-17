"""Usage persistence.

Persistence is out of scope for this exercise, but the calculation and
invoicing layers must never talk to a concrete storage type directly -- they
depend on the ``UsageStore`` interface, so a database-backed implementation
can be swapped in later without touching pricing or invoice code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, List

from .models import UsageEvent


class UsageStore(ABC):
    """Abstract usage store. Any implementation must support out-of-order
    ingestion: events may be added in any timestamp order, and queries must
    return correct results regardless of insertion order."""

    @abstractmethod
    def add_event(self, event: UsageEvent) -> None:
        """Record a single usage event."""

    @abstractmethod
    def add_events(self, events: Iterable[UsageEvent]) -> None:
        """Record a batch of usage events."""

    @abstractmethod
    def query(
        self,
        user_id: str,
        start: datetime,
        end: datetime,
    ) -> List[UsageEvent]:
        """Return all events for ``user_id`` with ``start <= timestamp < end``,
        ordered by timestamp ascending. The half-open interval means an event
        exactly on ``end`` belongs to the *next* period, never this one."""


class InMemoryUsageStore(UsageStore):
    """Simple in-memory implementation. Events are kept in insertion order
    internally, but ``query`` never relies on that order for correctness --
    it always filters by timestamp and re-sorts before returning."""

    def __init__(self) -> None:
        self._events_by_user: dict[str, list[UsageEvent]] = {}

    def add_event(self, event: UsageEvent) -> None:
        self._events_by_user.setdefault(event.user_id, []).append(event)

    def add_events(self, events: Iterable[UsageEvent]) -> None:
        for event in events:
            self.add_event(event)

    def query(self, user_id: str, start: datetime, end: datetime) -> List[UsageEvent]:
        if end <= start:
            raise ValueError("billing period end must be after start")
        events = self._events_by_user.get(user_id, [])
        in_period = [e for e in events if start <= e.timestamp < end]
        return sorted(in_period, key=lambda e: (e.timestamp, e.event_id))
