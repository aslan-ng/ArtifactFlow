"""The workflow and event history for one project."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from artifactflow.project.log import (
    ArtifactAvailable,
    Log,
    ProjectEvent,
    TargetsAccepted,
    ToolFailed,
    ToolSucceeded,
)
from artifactflow.tool.tool import Tool
from artifactflow.workflow.workflow import Workflow


@dataclass(frozen=True, slots=True)
class ProjectState:
    """Persistent facts reconstructed from the project's event history."""

    available_artifacts: frozenset[str]
    produced_artifacts: frozenset[str]
    successful_tools: tuple[str, ...]
    failed_attempts: tuple[str, ...]
    targets_accepted: bool


class Project:
    """
    Hold the definition and history of one workflow project.

    A project starts with an empty log. Artifacts supplied from outside,
    successful tool calls, and target acceptance are recorded one by one.
    The project stores those facts; an ``Advisor`` decides what to do next.
    """

    def __init__(
        self,
        workflow: Workflow,
        starting_artifacts: Iterable[str] | None = None,
        target_artifacts: Iterable[str] | None = None,
    ) -> None:
        self.workflow = workflow
        self.starting_artifacts = self._resolve_artifacts(
            "starting_artifacts",
            starting_artifacts,
            workflow.starting_artifacts,
        )
        self.target_artifacts = self._resolve_artifacts(
            "target_artifacts",
            target_artifacts,
            workflow.target_artifacts,
        )
        self.log = Log()

        self._validate_artifacts(
            set(self.starting_artifacts) | set(self.target_artifacts)
        )
        if not self.target_artifacts:
            raise ValueError("target_artifacts cannot be empty.")

    @property
    def events(self) -> tuple[ProjectEvent, ...]:
        """Return the complete, ordered project history."""
        return self.log.events

    @property
    def state(self) -> ProjectState:
        """Reconstruct the factual state from the complete event history."""
        available_artifacts: set[str] = set()
        produced_artifacts: set[str] = set()
        successful_tools: list[str] = []
        failed_attempts: list[str] = []
        targets_accepted = False

        for event in self.log:
            if isinstance(event, ArtifactAvailable):
                available_artifacts.add(event.artifact_name)
            elif isinstance(event, ToolSucceeded):
                tool = self.tool(event.tool_name)
                input_names = {
                    artifact.name
                    for artifact in tool.inputs
                }
                output_names = {
                    artifact.name
                    for artifact in tool.outputs
                }

                # Success is evidence that the tool's inputs were available.
                available_artifacts.update(input_names)
                available_artifacts.update(output_names)
                produced_artifacts.update(output_names)
                successful_tools.append(tool.name)
            elif isinstance(event, ToolFailed):
                failed_attempts.append(event.tool_name)
            elif isinstance(event, TargetsAccepted):
                targets_accepted = True

        return ProjectState(
            available_artifacts=frozenset(available_artifacts),
            produced_artifacts=frozenset(produced_artifacts),
            successful_tools=tuple(successful_tools),
            failed_attempts=tuple(failed_attempts),
            targets_accepted=targets_accepted,
        )

    @property
    def available_artifacts(self) -> frozenset[str]:
        """Return artifacts known to be available at least once."""
        return self.state.available_artifacts

    def record_artifact_available(self, artifact_name: str) -> None:
        """Record an artifact obtained outside the workflow."""
        self._validate_artifacts({artifact_name})
        self.log.artifact_available(artifact_name)

    def record_tool_success(self, tool_name: str) -> None:
        """Record a tool after its call has succeeded."""
        self.tool(tool_name)
        self.log.tool_succeeded(tool_name)

    def record_tool_failure(
        self,
        tool_name: str,
        reason: str | None = None,
    ) -> None:
        """Record one failed attempt to run a tool."""
        self.tool(tool_name)
        self.log.tool_failed(tool_name, reason)

    def record_target_acceptance(self) -> None:
        """Record external acceptance of the current target artifacts."""
        self.log.targets_accepted()

    def tool(self, tool_name: str) -> Tool:
        """Return a workflow tool by name."""
        for tool in self.workflow.tools:
            if tool.name == tool_name:
                return tool
        raise ValueError(f"Unknown tool: {tool_name!r}")

    def ordered_artifacts(
        self,
        artifact_names: Iterable[str],
    ) -> tuple[str, ...]:
        """Order artifact names as they occur in the workflow graph."""
        names = set(artifact_names)
        return tuple(
            artifact_name
            for artifact_name in self.workflow.artifact_names
            if artifact_name in names
        )

    def _validate_artifacts(self, artifact_names: set[str]) -> None:
        unknown = artifact_names - set(self.workflow.artifact_names)
        if unknown:
            raise ValueError(f"Unknown artifacts: {sorted(unknown)}")

    @staticmethod
    def _resolve_artifacts(
        name: str,
        project_value: Iterable[str] | None,
        workflow_value: Iterable[str] | None,
    ) -> tuple[str, ...]:
        value = project_value if project_value is not None else workflow_value
        if value is None:
            raise ValueError(
                f"{name} must be provided because the workflow does not "
                "define it."
            )
        return tuple(dict.fromkeys(value))
