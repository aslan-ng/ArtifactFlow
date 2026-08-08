"""The canonical execution history for one project."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass


def _validate_name(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


@dataclass(frozen=True, slots=True)
class FileReference:
    """A reference to one immutable, version-specific file."""

    location: str
    name: str = ""
    digest: str | None = None

    def __post_init__(self) -> None:
        _validate_name(self.location, "location")

        if not isinstance(self.name, str):
            raise TypeError("name must be a string.")

        if not self.name.strip():
            location = self.location.rstrip("/\\").replace("\\", "/")
            name = location.rsplit("/", 1)[-1]
            if not name:
                raise ValueError(
                    "name is required when location has no basename."
                )
            object.__setattr__(self, "name", name)
        else:
            _validate_name(self.name, "name")

        if self.digest is not None:
            _validate_name(self.digest, "digest")


@dataclass(frozen=True, slots=True)
class ArtifactOutput:
    """An unversioned artifact value returned by a successful tool."""

    artifact_name: str
    value: object | None = None
    file: FileReference | None = None

    def __post_init__(self) -> None:
        _validate_name(self.artifact_name, "artifact_name")
        if self.value is not None and self.file is not None:
            raise ValueError("An artifact cannot have both a value and a file.")
        if self.file is not None and not isinstance(
            self.file,
            FileReference,
        ):
            raise TypeError("file must be a FileReference or None.")


@dataclass(frozen=True, slots=True)
class ArtifactVersion:
    """One immutable occurrence of a named artifact."""

    artifact_name: str
    version: int
    value: object | None = None
    file: FileReference | None = None

    def __post_init__(self) -> None:
        _validate_name(self.artifact_name, "artifact_name")
        if isinstance(self.version, bool) or not isinstance(
            self.version,
            int,
        ):
            raise TypeError("version must be an integer.")
        if self.version < 1:
            raise ValueError("version must be a positive integer.")
        if self.value is not None and self.file is not None:
            raise ValueError("An artifact cannot have both a value and a file.")
        if self.file is not None and not isinstance(
            self.file,
            FileReference,
        ):
            raise TypeError("file must be a FileReference or None.")


@dataclass(frozen=True, slots=True)
class ArtifactAvailable:
    """An artifact version was obtained outside the workflow."""

    artifact: ArtifactVersion

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ArtifactVersion):
            raise TypeError("artifact must be an ArtifactVersion.")

    @property
    def artifact_name(self) -> str:
        """Return the workflow artifact name for compatibility."""
        return self.artifact.artifact_name


@dataclass(frozen=True, slots=True)
class ToolSucceeded:
    """A tool completed using exact inputs and created new outputs."""

    tool_name: str
    inputs: tuple[ArtifactVersion, ...] = ()
    outputs: tuple[ArtifactVersion, ...] = ()

    def __post_init__(self) -> None:
        _validate_name(self.tool_name, "tool_name")
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        if not all(
            isinstance(artifact, ArtifactVersion)
            for artifact in self.inputs + self.outputs
        ):
            raise TypeError(
                "inputs and outputs must contain ArtifactVersion objects."
            )


@dataclass(frozen=True, slots=True)
class ToolFailed:
    """One tool attempt failed after using the recorded inputs."""

    tool_name: str
    reason: str | None = None
    inputs: tuple[ArtifactVersion, ...] = ()

    def __post_init__(self) -> None:
        _validate_name(self.tool_name, "tool_name")
        object.__setattr__(self, "inputs", tuple(self.inputs))
        if not all(
            isinstance(artifact, ArtifactVersion)
            for artifact in self.inputs
        ):
            raise TypeError("inputs must contain ArtifactVersion objects.")
        if self.reason is not None and not isinstance(self.reason, str):
            raise TypeError("reason must be a string or None.")


@dataclass(frozen=True, slots=True)
class TargetsAccepted:
    """The recorded target versions passed the project checks."""

    targets: tuple[ArtifactVersion, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "targets", tuple(self.targets))
        if not all(
            isinstance(artifact, ArtifactVersion)
            for artifact in self.targets
        ):
            raise TypeError("targets must contain ArtifactVersion objects.")


ProjectEvent = (
    ArtifactAvailable
    | ToolSucceeded
    | ToolFailed
    | TargetsAccepted
)


class ExecutionLog:
    """An ordered, append-only collection of observed project events.

    Client-specific adapters translate raw LLM or MCP activity into these
    records. This class deliberately stores only normalized execution facts;
    it does not parse chat logs or decide which tool should run next.
    """

    def __init__(self) -> None:
        self._events: list[ProjectEvent] = []
        self._history: dict[str, list[ArtifactVersion]] = {}
        self._artifacts: dict[tuple[str, int], ArtifactVersion] = {}

    @property
    def events(self) -> tuple[ProjectEvent, ...]:
        """Return an immutable view of the complete event history."""
        return tuple(self._events)

    def append(self, event: ProjectEvent) -> None:
        """Validate and atomically append one observed event."""
        if not isinstance(
            event,
            (
                ArtifactAvailable,
                ToolSucceeded,
                ToolFailed,
                TargetsAccepted,
            ),
        ):
            raise TypeError("An execution log only accepts project events.")

        new_artifacts: tuple[ArtifactVersion, ...]
        if isinstance(event, ArtifactAvailable):
            new_artifacts = (event.artifact,)
        elif isinstance(event, ToolSucceeded):
            self._validate_existing(event.inputs, "input")
            new_artifacts = event.outputs
        elif isinstance(event, ToolFailed):
            self._validate_existing(event.inputs, "input")
            new_artifacts = ()
        else:
            self._validate_existing(event.targets, "target")
            new_artifacts = ()

        self._validate_new_versions(new_artifacts)

        # Nothing mutates until the entire event has passed validation.
        self._events.append(event)
        for artifact in new_artifacts:
            self._history.setdefault(artifact.artifact_name, []).append(
                artifact
            )
            self._artifacts[
                (artifact.artifact_name, artifact.version)
            ] = artifact

    def artifact_available(
        self,
        artifact_name: str,
        value: object | None = None,
        file: FileReference | None = None,
    ) -> ArtifactVersion:
        """Record and return the next externally supplied version."""
        artifact = ArtifactVersion(
            artifact_name=artifact_name,
            version=self._next_version(artifact_name),
            value=value,
            file=file,
        )
        self.append(ArtifactAvailable(artifact))
        return artifact

    def tool_succeeded(
        self,
        tool_name: str,
        inputs: Iterable[ArtifactVersion] = (),
        outputs: Iterable[ArtifactOutput] = (),
    ) -> ToolSucceeded:
        """Record a successful call and assign versions to its outputs."""
        input_versions = tuple(inputs)
        output_values = tuple(outputs)
        if not all(
            isinstance(output, ArtifactOutput)
            for output in output_values
        ):
            raise TypeError("outputs must contain ArtifactOutput objects.")

        next_versions: dict[str, int] = {}
        output_versions: list[ArtifactVersion] = []
        for output in output_values:
            version = next_versions.get(
                output.artifact_name,
                self._next_version(output.artifact_name),
            )
            output_versions.append(
                ArtifactVersion(
                    artifact_name=output.artifact_name,
                    version=version,
                    value=output.value,
                    file=output.file,
                )
            )
            next_versions[output.artifact_name] = version + 1

        event = ToolSucceeded(
            tool_name=tool_name,
            inputs=input_versions,
            outputs=tuple(output_versions),
        )
        self.append(event)
        return event

    def tool_failed(
        self,
        tool_name: str,
        reason: str | None = None,
        inputs: Iterable[ArtifactVersion] = (),
    ) -> ToolFailed:
        """Record and return one failed tool attempt."""
        event = ToolFailed(
            tool_name=tool_name,
            reason=reason,
            inputs=tuple(inputs),
        )
        self.append(event)
        return event

    def targets_accepted(
        self,
        targets: Iterable[ArtifactVersion] = (),
    ) -> TargetsAccepted:
        """Record acceptance of exact target versions."""
        event = TargetsAccepted(tuple(targets))
        self.append(event)
        return event

    def history(self, artifact_name: str) -> tuple[ArtifactVersion, ...]:
        """Return every recorded version of an artifact in order."""
        return tuple(self._history.get(artifact_name, ()))

    def latest_recorded(
        self,
        artifact_name: str,
    ) -> ArtifactVersion | None:
        """Return the latest recorded version, or None when absent.

        This is a history-wide lookup. During recovery, the Advisor may use
        an older version that belongs to the restored active route.
        """
        versions = self._history.get(artifact_name)
        return versions[-1] if versions else None

    def latest(self, artifact_name: str) -> ArtifactVersion | None:
        """Short alias for :meth:`latest_recorded`."""
        return self.latest_recorded(artifact_name)

    def artifact(
        self,
        artifact_name: str,
        version: int,
    ) -> ArtifactVersion:
        """Return one exact artifact version."""
        try:
            return self._artifacts[(artifact_name, version)]
        except KeyError:
            raise KeyError(
                f"Unknown artifact version: {artifact_name!r} v{version}."
            ) from None

    def _next_version(self, artifact_name: str) -> int:
        latest = self.latest(artifact_name)
        return 1 if latest is None else latest.version + 1

    def _validate_existing(
        self,
        artifacts: tuple[ArtifactVersion, ...],
        role: str,
    ) -> None:
        for artifact in artifacts:
            recorded = self._artifacts.get(
                (artifact.artifact_name, artifact.version)
            )
            if recorded is None:
                raise ValueError(
                    f"Unknown {role} artifact version: "
                    f"{artifact.artifact_name!r} v{artifact.version}."
                )
            if recorded != artifact:
                raise ValueError(
                    f"The {role} artifact does not match the recorded "
                    f"version: {artifact.artifact_name!r} "
                    f"v{artifact.version}."
                )

    def _validate_new_versions(
        self,
        artifacts: tuple[ArtifactVersion, ...],
    ) -> None:
        names = [artifact.artifact_name for artifact in artifacts]
        if len(names) != len(set(names)):
            raise ValueError(
                "One event can create at most one version of each artifact."
            )

        next_versions: dict[str, int] = {}
        for artifact in artifacts:
            expected = next_versions.get(
                artifact.artifact_name,
                self._next_version(artifact.artifact_name),
            )
            if artifact.version != expected:
                raise ValueError(
                    f"Expected {artifact.artifact_name!r} version "
                    f"{expected}, received version {artifact.version}."
                )
            next_versions[artifact.artifact_name] = expected + 1

    def __iter__(self) -> Iterator[ProjectEvent]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)


# Backward-compatible name for the original in-memory log.
Log = ExecutionLog
