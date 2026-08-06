"""Directions for progressing through an artifact workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from artifactflow.project.log import ArtifactAvailable, TargetsAccepted
from artifactflow.project.project import Project
from artifactflow.tool.tool import Tool


@dataclass(frozen=True, slots=True)
class ToolOption:
    """One tool the caller may choose next."""

    tool_name: str
    input_artifacts: tuple[str, ...]
    required_artifacts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdvisorCommand:
    """One self-contained direction returned by the advisor."""

    status: Literal["COMMAND", "COMPLETE"]
    options: tuple[ToolOption, ...] = ()
    suggested_artifacts: tuple[str, ...] = ()
    target_artifacts: tuple[str, ...] = ()
    message: str = ""
    return_when: str | None = None


@dataclass(slots=True)
class _AdviceState:
    """Navigation state reconstructed while reading the project log."""

    available_artifacts: set[str]
    produced_artifacts: set[str]
    next_tools: tuple[str, ...]
    targets_accepted: bool = False


class Advisor:
    """
    Read a project and say what should happen next.

    ``advise`` is the single method intended for a future MCP tool. When it
    returns several tool options, they are alternative route choices. The
    advisor has no recovery or parallel-execution policy in this initial
    implementation. A target candidate requires acceptance only when a
    continuation route can produce a fresh candidate.
    """

    def __init__(self, project: Project) -> None:
        self.project = project
        self._tool_positions = {
            tool.name: position
            for position, tool in enumerate(project.workflow.tools)
        }

        routes = self._bootstrap_routes(self._initial_state())
        if not routes:
            raise ValueError(
                "The workflow has no route from its starting artifacts "
                "to all target artifacts."
            )

        all_bootstrap = set().union(*routes)
        mandatory_bootstrap = set.intersection(
            *(set(route) for route in routes)
        )
        self._bootstrap_artifacts = project.ordered_artifacts(all_bootstrap)
        self._mandatory_bootstrap_artifacts = project.ordered_artifacts(
            mandatory_bootstrap
        )
        self._conditional_bootstrap_artifacts = project.ordered_artifacts(
            all_bootstrap - mandatory_bootstrap
        )

    @property
    def bootstrap_artifacts(self) -> tuple[str, ...]:
        """Return artifacts bootstrapped on at least one possible route."""
        return self._bootstrap_artifacts

    @property
    def mandatory_bootstrap_artifacts(self) -> tuple[str, ...]:
        """Return bootstrap artifacts required by every possible route."""
        return self._mandatory_bootstrap_artifacts

    @property
    def conditional_bootstrap_artifacts(self) -> tuple[str, ...]:
        """Return bootstrap artifacts required only by some routes."""
        return self._conditional_bootstrap_artifacts

    def advise(self) -> AdvisorCommand:
        """Return the next direction based on the complete project log."""
        state = self._replay_log()
        targets_ready = self._targets_ready(state)
        acceptance_required = self._acceptance_required(state)

        if targets_ready and (
            not acceptance_required
            or state.targets_accepted
        ):
            return AdvisorCommand(
                status="COMPLETE",
                target_artifacts=self.project.target_artifacts,
                message="The project is complete.",
            )

        if not state.next_tools and not targets_ready:
            raise RuntimeError("No tool can continue the selected route.")

        options = tuple(
            self._tool_option(tool_name, state.available_artifacts)
            for tool_name in state.next_tools
        )
        required_now = {
            artifact_name
            for option in options
            for artifact_name in option.required_artifacts
        }

        remaining_routes = self._bootstrap_routes(state)
        mandatory_later: set[str] = set()
        if remaining_routes:
            mandatory_later = set.intersection(
                *(set(route) for route in remaining_routes)
            )

        suggested_artifacts = self.project.ordered_artifacts(
            mandatory_later
            - state.available_artifacts
            - required_now
        )

        if targets_ready:
            message = (
                "The target artifacts are ready. Accept them if they meet "
                "the project conditions, or choose a tool to continue."
            )
            return_when = (
                "after accepting the targets or one listed tool succeeds"
            )
        else:
            message = (
                "Choose one tool, obtain its required artifacts, and run "
                "the tool until it succeeds. Then ask for advice again."
            )
            return_when = "after one listed tool succeeds"

        return AdvisorCommand(
            status="COMMAND",
            options=options,
            suggested_artifacts=suggested_artifacts,
            target_artifacts=(
                self.project.target_artifacts
                if targets_ready
                else ()
            ),
            message=message,
            return_when=return_when,
        )

    def _replay_log(self) -> _AdviceState:
        state = self._initial_state()

        for event in self.project.events:
            targets_ready = self._targets_ready(state)
            if state.targets_accepted or (
                targets_ready
                and not self._acceptance_required(state)
            ):
                raise ValueError(
                    "The project log contains work after completion."
                )

            if isinstance(event, ArtifactAvailable):
                if event.artifact_name not in self.project.workflow.artifact_names:
                    raise ValueError(
                        f"Unknown artifact: {event.artifact_name!r}"
                    )
                state.available_artifacts.add(event.artifact_name)
                continue

            if isinstance(event, TargetsAccepted):
                if not targets_ready:
                    raise ValueError(
                        "Target artifacts cannot be accepted before they "
                        "are produced."
                    )
                state.targets_accepted = True
                continue

            if event.tool_name not in state.next_tools:
                raise ValueError(
                    f"Tool {event.tool_name!r} was not an advised option."
                )

            state = self._after_tool(state, self.project.tool(event.tool_name))

        return state

    def _initial_state(self) -> _AdviceState:
        starting_tools = tuple(
            tool.name
            for tool in self.project.workflow.tools
            if self._can_start(tool)
        )
        return _AdviceState(
            available_artifacts=set(),
            produced_artifacts=set(),
            next_tools=starting_tools,
        )

    def _can_start(self, tool: Tool) -> bool:
        """
        Return whether a tool belongs to the initial frontier.

        Workflow insertion order resolves an input that also has a producer:
        an earlier producer must run before the consuming tool can start.
        """
        if not tool.inputs:
            return True

        starting_artifacts = set(self.project.starting_artifacts)
        if not any(
            artifact.name in starting_artifacts
            for artifact in tool.inputs
        ):
            return False

        for artifact in tool.inputs:
            if artifact.name in starting_artifacts:
                continue

            for producer_name in self.project.workflow.G.predecessors(
                artifact.name
            ):
                if (
                    self._tool_positions[producer_name]
                    < self._tool_positions[tool.name]
                ):
                    return False

        return True

    def _after_tool(
        self,
        state: _AdviceState,
        tool: Tool,
    ) -> _AdviceState:
        input_names = {artifact.name for artifact in tool.inputs}
        output_names = {artifact.name for artifact in tool.outputs}

        available_artifacts = set(state.available_artifacts)
        available_artifacts.update(input_names)
        available_artifacts.update(output_names)

        produced_artifacts = set(state.produced_artifacts)
        if self._targets_ready(state):
            # Continuing means the previous candidate targets were rejected.
            produced_artifacts.difference_update(
                self.project.target_artifacts
            )
        produced_artifacts.update(output_names)

        return _AdviceState(
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
            for tool in self.project.workflow.tools
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
        tool = self.project.tool(tool_name)
        input_artifacts = tuple(
            artifact.name
            for artifact in tool.inputs
        )
        return ToolOption(
            tool_name=tool.name,
            input_artifacts=input_artifacts,
            required_artifacts=tuple(
                artifact_name
                for artifact_name in input_artifacts
                if artifact_name not in available_artifacts
            ),
        )

    def _bootstrap_routes(
        self,
        state: _AdviceState,
        visits: dict[tuple, int] | None = None,
    ) -> tuple[frozenset[str], ...]:
        """Return the missing external artifacts for each remaining route."""
        if self._targets_ready(state):
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
            tool = self.project.tool(tool_name)
            missing_inputs = {
                artifact.name
                for artifact in tool.inputs
                if artifact.name not in state.available_artifacts
            }
            next_state = self._after_tool(state, tool)
            for remaining in self._bootstrap_routes(next_state, visits):
                routes.append(frozenset(missing_inputs) | remaining)

        return tuple(dict.fromkeys(routes))

    def _targets_ready(self, state: _AdviceState) -> bool:
        return (
            set(self.project.target_artifacts)
            <= state.produced_artifacts
        )

    def _acceptance_required(self, state: _AdviceState) -> bool:
        """Return whether a continuation can produce a fresh candidate."""
        if not self._targets_ready(state) or not state.next_tools:
            return False

        continuation = _AdviceState(
            available_artifacts=set(state.available_artifacts),
            produced_artifacts=(
                set(state.produced_artifacts)
                - set(self.project.target_artifacts)
            ),
            next_tools=state.next_tools,
        )
        return bool(self._bootstrap_routes(continuation))
