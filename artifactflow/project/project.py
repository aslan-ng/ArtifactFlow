"""A simple advisor for executing an artifact workflow."""

from __future__ import annotations

from dataclasses import dataclass

from artifactflow.project.log import ArtifactAvailable, Log, ToolSucceeded
from artifactflow.tool.tool import Tool
from artifactflow.workflow.workflow import Workflow


@dataclass(frozen=True, slots=True)
class ArtifactRequirement:
    """An unavailable artifact that must be obtained before a tool runs."""

    artifact_name: str
    bootstrap: bool = True


@dataclass(frozen=True, slots=True)
class BootstrapSuggestion:
    """A non-blocking artifact suggestion for a later tool."""

    artifact_name: str


@dataclass(frozen=True, slots=True)
class ToolOption:
    """One tool the advisor permits the caller to choose next."""

    tool_name: str
    input_artifacts: tuple[str, ...]
    required_artifacts: tuple[ArtifactRequirement, ...]


@dataclass(frozen=True, slots=True)
class AdvisorCommand:
    """The next instruction returned to the LLM."""

    status: str
    options: tuple[ToolOption, ...] = ()
    suggestions: tuple[BootstrapSuggestion, ...] = ()
    target_artifacts: tuple[str, ...] = ()
    message: str = ""
    return_when: str | None = None


@dataclass(slots=True)
class _ProjectState:
    """State reconstructed from the project log."""

    available_artifacts: set[str]
    produced_artifacts: set[str]
    next_tools: tuple[str, ...]


class Project:
    """
    Advise an LLM which workflow tool to use next.

    The project owns an initially empty log. Tool calls and externally
    obtained artifacts are added to that log. ``advise`` replays the log, so
    the log is the complete explanation of project progress.

    When several tools are returned, they are alternative route choices.
    Parallel execution is intentionally outside this first implementation.
    """

    def __init__(
        self,
        workflow: Workflow,
        ready_artifacts: list[str] | None = None,
        starting_artifacts: list[str] | None = None,
        target_artifacts: list[str] | None = None,
    ) -> None:
        self.workflow = workflow
        self.starting_artifacts = self._project_artifacts(
            "starting_artifacts",
            starting_artifacts,
            workflow.starting_artifacts,
        )
        self.target_artifacts = self._project_artifacts(
            "target_artifacts",
            target_artifacts,
            workflow.target_artifacts,
        )
        self.initial_artifacts = set(ready_artifacts or [])
        self.log = Log()

        self._validate_artifacts(
            self.initial_artifacts
            | set(self.starting_artifacts)
            | set(self.target_artifacts)
        )

        empty_state = self._initial_state(available_artifacts=set())
        bootstrap_routes = self._bootstrap_routes(empty_state)
        if not bootstrap_routes:
            raise ValueError(
                "The workflow has no route from its starting artifacts "
                "to all target artifacts."
            )

        all_bootstrap = set().union(*bootstrap_routes)
        mandatory_bootstrap = set.intersection(
            *(set(route) for route in bootstrap_routes)
        )
        self._bootstrap_artifacts = self._ordered_artifacts(all_bootstrap)
        self._mandatory_bootstrap_artifacts = self._ordered_artifacts(
            mandatory_bootstrap
        )
        self._conditional_bootstrap_artifacts = self._ordered_artifacts(
            all_bootstrap - mandatory_bootstrap
        )

    @property
    def bootstrap_artifacts(self) -> tuple[str, ...]:
        """Artifacts bootstrapped by at least one possible route."""
        return self._bootstrap_artifacts

    @property
    def mandatory_bootstrap_artifacts(self) -> tuple[str, ...]:
        """Bootstrap artifacts required by every possible route."""
        return self._mandatory_bootstrap_artifacts

    @property
    def conditional_bootstrap_artifacts(self) -> tuple[str, ...]:
        """Bootstrap artifacts required by only some possible routes."""
        return self._conditional_bootstrap_artifacts

    @property
    def available_artifacts(self) -> frozenset[str]:
        """Artifacts currently available according to the project log."""
        return frozenset(self._replay_log().available_artifacts)

    def advise(self) -> AdvisorCommand:
        """Read the log and return the next command for the LLM."""
        state = self._replay_log()

        if set(self.target_artifacts) <= state.produced_artifacts:
            return AdvisorCommand(
                status="COMPLETE",
                target_artifacts=tuple(self.target_artifacts),
                message="The project is complete.",
            )

        if not state.next_tools:
            raise RuntimeError("No tool can continue the selected route.")

        options = tuple(
            self._tool_option(tool_name, state.available_artifacts)
            for tool_name in state.next_tools
        )
        required_now = {
            requirement.artifact_name
            for option in options
            for requirement in option.required_artifacts
        }

        remaining_routes = self._bootstrap_routes(state)
        mandatory_later: set[str] = set()
        if remaining_routes:
            mandatory_later = set.intersection(
                *(set(route) for route in remaining_routes)
            )

        suggested_artifacts = (
            mandatory_later
            - state.available_artifacts
            - required_now
        )
        suggestions = tuple(
            BootstrapSuggestion(artifact_name)
            for artifact_name in self._ordered_artifacts(
                suggested_artifacts
            )
        )

        return AdvisorCommand(
            status="COMMAND",
            options=options,
            suggestions=suggestions,
            message=(
                "Choose one tool, obtain its required artifacts, and run "
                "the tool until it succeeds. Then ask for advice again."
            ),
            return_when="after one of the listed tools succeeds",
        )

    def _replay_log(self) -> _ProjectState:
        state = self._initial_state(set(self.initial_artifacts))

        for event in self.log:
            if isinstance(event, ArtifactAvailable):
                self._validate_artifacts({event.artifact_name})
                state.available_artifacts.add(event.artifact_name)
                continue

            if set(self.target_artifacts) <= state.produced_artifacts:
                raise ValueError("The log contains work after project completion.")

            if event.tool_name not in state.next_tools:
                raise ValueError(
                    f"Tool {event.tool_name!r} was not an advised option."
                )

            state = self._after_tool(state, self._tool(event.tool_name))

        return state

    def _initial_state(
        self,
        available_artifacts: set[str],
    ) -> _ProjectState:
        starting_tools = [
            tool.name
            for tool in self.workflow.tools
            if not tool.inputs
            or any(
                artifact.name in self.starting_artifacts
                for artifact in tool.inputs
            )
        ]
        return _ProjectState(
            available_artifacts=available_artifacts,
            produced_artifacts=set(),
            next_tools=tuple(starting_tools),
        )

    def _after_tool(
        self,
        state: _ProjectState,
        tool: Tool,
    ) -> _ProjectState:
        input_names = {artifact.name for artifact in tool.inputs}
        output_names = {artifact.name for artifact in tool.outputs}

        # A successful call proves that all requested inputs existed.
        available_artifacts = set(state.available_artifacts)
        available_artifacts.update(input_names)
        available_artifacts.update(output_names)

        produced_artifacts = set(state.produced_artifacts)
        produced_artifacts.update(output_names)

        return _ProjectState(
            available_artifacts=available_artifacts,
            produced_artifacts=produced_artifacts,
            next_tools=self._following_tools(output_names),
        )

    def _following_tools(
        self,
        output_artifacts: set[str],
    ) -> tuple[str, ...]:
        return tuple(
            tool.name
            for tool in self.workflow.tools
            if any(
                artifact.name in output_artifacts
                for artifact in tool.inputs
            )
        )

    def _tool_option(
        self,
        tool_name: str,
        available_artifacts: set[str],
    ) -> ToolOption:
        tool = self._tool(tool_name)
        input_artifacts = tuple(
            artifact.name
            for artifact in tool.inputs
        )
        required_artifacts = tuple(
            ArtifactRequirement(artifact_name)
            for artifact_name in input_artifacts
            if artifact_name not in available_artifacts
        )
        return ToolOption(
            tool_name=tool.name,
            input_artifacts=input_artifacts,
            required_artifacts=required_artifacts,
        )

    def _bootstrap_routes(
        self,
        state: _ProjectState,
        visits: dict[tuple, int] | None = None,
    ) -> tuple[frozenset[str], ...]:
        """
        Return the remaining bootstrap set for each route to the targets.

        A state may be visited twice so one pass through a cycle can be
        considered. More repetitions cannot introduce a new artifact name.
        """
        if set(self.target_artifacts) <= state.produced_artifacts:
            return (frozenset(),)

        state_key = (
            state.next_tools,
            frozenset(state.available_artifacts),
            frozenset(state.produced_artifacts),
        )
        visits = dict(visits or {})
        if visits.get(state_key, 0) >= 2:
            return ()
        visits[state_key] = visits.get(state_key, 0) + 1

        routes: list[frozenset[str]] = []
        for tool_name in state.next_tools:
            tool = self._tool(tool_name)
            missing_inputs = {
                artifact.name
                for artifact in tool.inputs
                if artifact.name not in state.available_artifacts
            }
            next_state = self._after_tool(state, tool)
            for remaining_bootstrap in self._bootstrap_routes(
                next_state,
                visits,
            ):
                routes.append(
                    frozenset(missing_inputs) | remaining_bootstrap
                )

        return tuple(dict.fromkeys(routes))

    def _tool(self, tool_name: str) -> Tool:
        for tool in self.workflow.tools:
            if tool.name == tool_name:
                return tool
        raise ValueError(f"Unknown tool: {tool_name!r}")

    def _ordered_artifacts(
        self,
        artifact_names: set[str],
    ) -> tuple[str, ...]:
        return tuple(
            artifact_name
            for artifact_name in self.workflow.artifact_names
            if artifact_name in artifact_names
        )

    def _validate_artifacts(self, artifact_names: set[str]) -> None:
        unknown_artifacts = artifact_names - set(self.workflow.artifact_names)
        if unknown_artifacts:
            raise ValueError(f"Unknown artifacts: {sorted(unknown_artifacts)}")

    @staticmethod
    def _project_artifacts(
        name: str,
        project_value: list[str] | None,
        workflow_value: list[str] | None,
    ) -> list[str]:
        value = project_value if project_value is not None else workflow_value
        if value is None:
            raise ValueError(
                f"{name} must be provided because the workflow does not "
                "define it."
            )
        return list(value)
