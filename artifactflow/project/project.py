"""The workflow definition and observed execution history of one project."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from artifactflow.plan.plan import Plan
from artifactflow.project.log import (
    ArtifactAvailable,
    ArtifactOutput,
    ArtifactVersion,
    ExecutionLog,
    FileReference,
    ProjectEvent,
    TargetsAccepted,
    ToolFailed,
    ToolSucceeded,
)
from artifactflow.tool.tool import Tool
from artifactflow.tool_network.tool_network import ToolNetwork
from artifactflow.workflow.workflow import Workflow


ActionLocation = Literal[
    "PROPOSED_PLAN",
    "WORKFLOW",
    "TOOL_NETWORK",
]


@dataclass(frozen=True, slots=True)
class ProjectState:
    """Factual history summary, independent of orchestration policy.

    ``latest_artifacts`` contains the newest version recorded anywhere in
    the history. During recovery, the Advisor may intentionally use an older
    version that belongs to the restored workflow route.
    """

    available_artifacts: frozenset[str]
    produced_artifacts: frozenset[str]
    latest_artifacts: Mapping[str, ArtifactVersion]
    successful_tools: tuple[str, ...]
    failed_attempts: tuple[str, ...]
    targets_accepted: bool


class Project:
    """Combine a workflow, its wider tool network, and an execution log.

    A project starts with an empty :class:`ExecutionLog` unless an existing
    log is injected. When no tool network is supplied, an exact network copy
    of the workflow is created. An observer or raw-log adapter records facts
    in the log; the Advisor reads those facts whenever advice is requested.
    """

    def __init__(
        self,
        workflow: Workflow,
        starting_artifacts: Iterable[str] | None = None,
        target_artifacts: Iterable[str] | None = None,
        execution_log: ExecutionLog | None = None,
        tool_network: ToolNetwork | None = None,
    ) -> None:
        self.workflow = workflow
        if tool_network is not None and not isinstance(
            tool_network,
            ToolNetwork,
        ):
            raise TypeError("tool_network must be a ToolNetwork or None.")
        self.tool_network = (
            tool_network
            if tool_network is not None
            else workflow.to_tool_network()
        )
        if not self.tool_network.contains_workflow(workflow):
            raise ValueError(
                "tool_network must contain the complete workflow."
            )

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
        self.execution_log = (
            execution_log
            if execution_log is not None
            else ExecutionLog()
        )

        # ``log`` remains a concise compatibility alias. New code can use
        # ``execution_log`` when the distinction from a raw LLM log matters.
        self.log = self.execution_log

        self._validate_workflow_artifacts(
            set(self.starting_artifacts) | set(self.target_artifacts)
        )
        if not self.target_artifacts:
            raise ValueError("target_artifacts cannot be empty.")

    @property
    def events(self) -> tuple[ProjectEvent, ...]:
        """Return the complete, ordered execution history."""
        return self.execution_log.events

    @property
    def state(self) -> ProjectState:
        """Reconstruct factual state from the complete execution history."""
        available_artifacts: set[str] = set()
        produced_artifacts: set[str] = set()
        latest_artifacts: dict[str, ArtifactVersion] = {}
        successful_tools: list[str] = []
        failed_attempts: list[str] = []
        targets_accepted = False

        for event in self.execution_log:
            if isinstance(event, ArtifactAvailable):
                artifact = event.artifact
                available_artifacts.add(artifact.artifact_name)
                latest_artifacts[artifact.artifact_name] = artifact
            elif isinstance(event, ToolSucceeded):
                available_artifacts.update(
                    artifact.artifact_name
                    for artifact in event.inputs
                )
                for artifact in event.outputs:
                    available_artifacts.add(artifact.artifact_name)
                    produced_artifacts.add(artifact.artifact_name)
                    latest_artifacts[artifact.artifact_name] = artifact
                successful_tools.append(event.tool_name)
            elif isinstance(event, ToolFailed):
                failed_attempts.append(event.tool_name)
            elif isinstance(event, TargetsAccepted):
                targets_accepted = True

        return ProjectState(
            available_artifacts=frozenset(available_artifacts),
            produced_artifacts=frozenset(produced_artifacts),
            latest_artifacts=dict(latest_artifacts),
            successful_tools=tuple(successful_tools),
            failed_attempts=tuple(failed_attempts),
            targets_accepted=targets_accepted,
        )

    @property
    def available_artifacts(self) -> frozenset[str]:
        """Return artifact names that have been usable at least once."""
        return self.state.available_artifacts

    def latest_artifact(
        self,
        artifact_name: str,
    ) -> ArtifactVersion | None:
        """Return the newest version anywhere in the execution history.

        This is useful for inspection. Advice uses route-aware versions
        reconstructed from the same log instead of blindly using this value.
        """
        self._validate_artifacts({artifact_name})
        return self.execution_log.latest(artifact_name)

    def record_artifact_available(
        self,
        artifact_name: str,
        *,
        value: object | None = None,
        file: FileReference | None = None,
    ) -> ArtifactVersion:
        """Record one artifact obtained outside the workflow."""
        self._validate_artifacts({artifact_name})
        return self.execution_log.artifact_available(
            artifact_name,
            value=value,
            file=file,
        )

    def record_tool_success(
        self,
        tool_name: str,
        *,
        inputs: Iterable[ArtifactVersion] | None = None,
        outputs: Iterable[ArtifactOutput] | None = None,
    ) -> ToolSucceeded:
        """Record one successful tool call and its concrete artifacts.

        An observer should pass the exact input versions and output values or
        files. Omitting them is a convenient shorthand for simulations: the
        newest recorded inputs are used and payload-free output versions are
        created from the workflow definition.
        """
        tool = self.tool(tool_name)
        input_versions = self._resolve_input_versions(tool, inputs)
        output_values = self._resolve_outputs(tool, outputs)
        return self.execution_log.tool_succeeded(
            tool_name,
            inputs=input_versions,
            outputs=output_values,
        )

    def record_tool_failure(
        self,
        tool_name: str,
        reason: str | None = None,
        *,
        inputs: Iterable[ArtifactVersion] | None = None,
    ) -> ToolFailed:
        """Record one failed tool attempt and the exact inputs it used."""
        tool = self.tool(tool_name)
        input_versions = self._resolve_input_versions(tool, inputs)
        return self.execution_log.tool_failed(
            tool_name,
            reason,
            inputs=input_versions,
        )

    def record_target_acceptance(
        self,
        targets: Iterable[ArtifactVersion] = (),
    ) -> TargetsAccepted:
        """Record acceptance, optionally naming exact target versions."""
        return self.execution_log.targets_accepted(targets)

    def tool(self, tool_name: str) -> Tool:
        """Return a known tool from the project's complete tool network."""
        for tool in self.tool_network.tools:
            if tool.name == tool_name:
                return tool
        raise ValueError(f"Unknown tool: {tool_name!r}")

    def classify_action(
        self,
        tool_name: str,
        proposed_plans: Iterable[Plan] = (),
    ) -> ActionLocation:
        """Locate an observed tool within the project's planning scopes.

        Classification is purely structural. The Advisor will later decide
        how to respond to an action outside its proposed plans.
        """
        plans = tuple(proposed_plans)
        if not all(isinstance(plan, Plan) for plan in plans):
            raise TypeError("proposed_plans must contain Plan objects.")

        if any(plan.contains_tool(tool_name) for plan in plans):
            return "PROPOSED_PLAN"
        if self.workflow.contains_tool(tool_name):
            return "WORKFLOW"
        if self.tool_network.contains_tool(tool_name):
            return "TOOL_NETWORK"
        raise ValueError(
            f"Unknown tool: {tool_name!r}. It is not part of the project's "
            "tool network."
        )

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

    def _resolve_input_versions(
        self,
        tool: Tool,
        inputs: Iterable[ArtifactVersion] | None,
    ) -> tuple[ArtifactVersion, ...]:
        expected_names = tuple(
            artifact.name
            for artifact in tool.inputs
        )

        if inputs is None:
            resolved: list[ArtifactVersion] = []
            for artifact_name in expected_names:
                artifact = self.execution_log.latest(artifact_name)
                if artifact is None:
                    # A call is evidence that this input existed, even when
                    # a lightweight observer did not capture its payload.
                    artifact = self.execution_log.artifact_available(
                        artifact_name
                    )
                resolved.append(artifact)
            return tuple(resolved)

        input_versions = tuple(inputs)
        actual_names = tuple(
            artifact.artifact_name
            for artifact in input_versions
        )
        if len(set(actual_names)) != len(actual_names):
            raise ValueError("A tool input artifact can be referenced once.")
        if set(actual_names) != set(expected_names):
            raise ValueError(
                f"Tool {tool.name!r} expects inputs {expected_names}, "
                f"not {actual_names}."
            )

        by_name = {
            artifact.artifact_name: artifact
            for artifact in input_versions
        }
        return tuple(by_name[name] for name in expected_names)

    @staticmethod
    def _resolve_outputs(
        tool: Tool,
        outputs: Iterable[ArtifactOutput] | None,
    ) -> tuple[ArtifactOutput, ...]:
        expected_names = tuple(
            artifact.name
            for artifact in tool.outputs
        )
        if outputs is None:
            return tuple(ArtifactOutput(name) for name in expected_names)

        output_values = tuple(outputs)
        actual_names = tuple(
            artifact.artifact_name
            for artifact in output_values
        )
        if len(set(actual_names)) != len(actual_names):
            raise ValueError("A tool can create one version per artifact.")
        if set(actual_names) != set(expected_names):
            raise ValueError(
                f"Tool {tool.name!r} declares outputs {expected_names}, "
                f"not {actual_names}."
            )

        by_name = {
            artifact.artifact_name: artifact
            for artifact in output_values
        }
        return tuple(by_name[name] for name in expected_names)

    def _validate_artifacts(self, artifact_names: set[str]) -> None:
        unknown = artifact_names - set(self.tool_network.artifact_names)
        if unknown:
            raise ValueError(f"Unknown artifacts: {sorted(unknown)}")

    def _validate_workflow_artifacts(
        self,
        artifact_names: set[str],
    ) -> None:
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
