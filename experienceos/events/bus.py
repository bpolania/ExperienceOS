"""Synchronous in-process event bus with history. No external brokers."""

from __future__ import annotations

from typing import Callable

from experienceos.events.schema import ExperienceEvent


class EventBus:
    """Publishes events to subscribers and keeps an in-memory history."""

    def __init__(self):
        self._history: list[ExperienceEvent] = []
        self._subscribers: list[Callable[[ExperienceEvent], None]] = []

    def subscribe(self, handler: Callable[[ExperienceEvent], None]) -> None:
        self._subscribers.append(handler)

    def publish(self, event: ExperienceEvent) -> ExperienceEvent:
        self._history.append(event)
        for handler in self._subscribers:
            handler(event)
        return event

    def emit(
        self,
        event_type: str,
        user_id: str,
        session_id: str,
        payload: dict | None = None,
    ) -> ExperienceEvent:
        """Build and publish an event in one step."""
        return self.publish(
            ExperienceEvent(
                type=event_type,
                user_id=user_id,
                session_id=session_id,
                payload=payload or {},
            )
        )

    def history(self) -> list[ExperienceEvent]:
        return list(self._history)

    def for_session(self, user_id: str, session_id: str) -> list[ExperienceEvent]:
        return [
            e
            for e in self._history
            if e.user_id == user_id and e.session_id == session_id
        ]

    def clear(self) -> None:
        self._history.clear()
