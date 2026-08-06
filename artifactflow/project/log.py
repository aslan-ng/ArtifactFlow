"""The small event log used by a project advisor."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtifactAvailable:
    """An artifact was obtained outside the workflow."""

    artifact_name: str


@dataclass(frozen=True, slots=True)
class ToolSucceeded:
    """A workflow tool completed successfully."""

    tool_name: str


ProjectEvent = ArtifactAvailable | ToolSucceeded


class Log:
    """An ordered, append-only collection of project events."""

    def __init__(self) -> None:
        self._events: list[ProjectEvent] = []

    @property
    def events(self) -> tuple[ProjectEvent, ...]:
        return tuple(self._events)

    def append(self, event: ProjectEvent) -> None:
        if not isinstance(event, (ArtifactAvailable, ToolSucceeded)):
            raise TypeError("A project log only accepts project events.")
        self._events.append(event)

    def artifact_available(self, artifact_name: str) -> None:
        """Record an artifact supplied by a user or another source."""
        self.append(ArtifactAvailable(artifact_name))

    def tool_succeeded(self, tool_name: str) -> None:
        """Record a successful tool call."""
        self.append(ToolSucceeded(tool_name))

    def __iter__(self):
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)
