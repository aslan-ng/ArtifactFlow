"""Directions for progressing through an artifact workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from artifactflow.project.log import (
    ArtifactAvailable,
    TargetsAccepted,
    ToolFailed,
    ToolSucceeded,
)
from artifactflow.project.project import Project
from artifactflow.tool.tool import Tool


@dataclass(frozen=True, slots=True)
class ToolOption:
    """One tool the caller may choose next."""

    tool_name: str
    input_artifacts: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    action: Literal["RUN", "RETRY", "ALTERNATIVE"] = "RUN"


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    """Why the Advisor is returning recovery options."""

    last_failed_tool: str | None
    last_failure_reason: str | None = None
    backtrack_depth: int = 0
    exhausted_options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdvisorCommand:
    """One self-contained direction returned by the Advisor."""

    status: Literal["COMMAND", "RECOVERY", "COMPLETE", "BLOCKED"]
    options: tuple[ToolOption, ...] = ()
    suggested_artifacts: tuple[str, ...] = ()
    target_artifacts: tuple[str, ...] = ()
    recovery: RecoveryContext | None = None
    message: str = ""
    return_when: str | None = None


@dataclass(slots=True)
class _AdviceState:
    """Active artifacts and tools at one point along the selected route."""

    available_artifacts: set[str]
    produced_artifacts: set[str]
    next_tools: tuple[str, ...]
    targets_accepted: bool = False


@dataclass(slots=True)
class _DecisionFrame:
    """A restorable tool choice encountered along the active route."""

    checkpoint: _AdviceState
    options: tuple[str, ...]
    exhausted_options: set[str] = field(default_factory=set)
    failure_counts: dict[str, int] = field(default_factory=dict)
    selected_option: str | None = None
    retry_tool: str | None = None


@dataclass(slots=True)
class _ReplayState:
    """State reconstructed from the complete project event log."""

    active: _AdviceState
    decisions: list[_DecisionFrame]
    external_artifacts: set[str]
    recovering: bool = False
    last_failed_tool: str | None = None
    last_failure_reason: str | None = None
    backtrack_depth: int = 0
    blocked: bool = False


class Advisor:
    """
    Read a project and say what should happen next.

    ``advise`` is the single method intended for a future MCP tool. Several
    tool options are alternative route choices, not parallel work.

    After a failed tool call, the Advisor permits one retry. A second failure
    exhausts that option. The Advisor then offers unchecked siblings or
    restores the nearest earlier decision point. A target candidate requires
    acceptance only when a continuation can produce a fresh candidate.
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
        replay = self._replay_log()
        state = replay.active
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

        if replay.blocked:
            return AdvisorCommand(
                status="BLOCKED",
                recovery=self._recovery_context(replay),
                message=(
                    "Every tool option and its retry have been exhausted. "
                    "The project is blocked."
                ),
            )

        tool_names = self._available_options(replay)
        if not tool_names:
            return AdvisorCommand(
                status="BLOCKED",
                message="No tool can continue the project.",
            )

        status: Literal["COMMAND", "RECOVERY"] = (
            "RECOVERY"
            if replay.recovering
            else "COMMAND"
        )
        options = tuple(
            self._tool_option(
                tool_name,
                state.available_artifacts,
                self._tool_action(replay, tool_name),
            )
            for tool_name in tool_names
        )

        command_state = self._copy_state(state)
        command_state.next_tools = tool_names
        required_now = {
            artifact_name
            for option in options
            for artifact_name in option.required_artifacts
        }
        remaining_routes = self._bootstrap_routes(command_state)
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

        if status == "RECOVERY":
            recovery = self._recovery_context(replay)
            if options[0].action == "RETRY":
                message = (
                    "The tool failed. Retry it once, then report whether "
                    "the retry succeeds or fails."
                )
            elif replay.backtrack_depth:
                message = (
                    "The current branch is exhausted. Choose an alternative "
                    "from the nearest earlier decision point."
                )
            else:
                message = (
                    "The tool and its retry failed. Choose another option "
                    "from the same decision point."
                )
            return_when = "after one listed tool succeeds or fails"
        elif targets_ready:
            recovery = None
            message = (
                "The target artifacts are ready. Accept them if they meet "
                "the project conditions, or choose a tool to continue."
            )
            return_when = (
                "after accepting the targets or one listed tool succeeds "
                "or fails"
            )
        else:
            recovery = None
            message = (
                "Choose one tool, obtain its required artifacts, and run it "
                "once. Record whether it succeeds or fails, then ask for "
                "advice again."
            )
            return_when = "after one listed tool succeeds or fails"

        return AdvisorCommand(
            status=status,
            options=options,
            suggested_artifacts=suggested_artifacts,
            target_artifacts=(
                self.project.target_artifacts
                if targets_ready
                else ()
            ),
            recovery=recovery,
            message=message,
            return_when=return_when,
        )

    def _replay_log(self) -> _ReplayState:
        initial_state = self._initial_state()
        replay = _ReplayState(
            active=initial_state,
            decisions=[],
            external_artifacts=set(),
        )
        self._push_decision(replay)

        for event in self.project.events:
            if self._is_complete(replay.active):
                raise ValueError(
                    "The project log contains work after completion."
                )
            if replay.blocked:
                raise ValueError(
                    "The project log contains work after it became blocked."
                )

            if isinstance(event, ArtifactAvailable):
                self._record_external_artifact(replay, event.artifact_name)
                continue

            if isinstance(event, TargetsAccepted):
                if not self._targets_ready(replay.active):
                    raise ValueError(
                        "Target artifacts cannot be accepted before they "
                        "are produced."
                    )
                replay.active.targets_accepted = True
                continue

            allowed_tools = self._available_options(replay)
            if event.tool_name not in allowed_tools:
                raise ValueError(
                    f"Tool {event.tool_name!r} was not an advised option."
                )

            self._reject_target_candidate(replay)

            if isinstance(event, ToolFailed):
                self._record_failure(replay, event)
            elif isinstance(event, ToolSucceeded):
                self._record_success(replay, event.tool_name)

        return replay

    def _record_external_artifact(
        self,
        replay: _ReplayState,
        artifact_name: str,
    ) -> None:
        if artifact_name not in self.project.workflow.artifact_names:
            raise ValueError(f"Unknown artifact: {artifact_name!r}")

        replay.external_artifacts.add(artifact_name)
        replay.active.available_artifacts.add(artifact_name)
        for decision in replay.decisions:
            decision.checkpoint.available_artifacts.add(artifact_name)

    def _record_failure(
        self,
        replay: _ReplayState,
        event: ToolFailed,
    ) -> None:
        tool_name = event.tool_name
        decision = replay.decisions[-1]
        failure_count = decision.failure_counts.get(tool_name, 0) + 1
        decision.failure_counts[tool_name] = failure_count

        replay.recovering = True
        replay.last_failed_tool = tool_name
        replay.last_failure_reason = event.reason
        replay.backtrack_depth = 0

        if failure_count == 1:
            decision.retry_tool = tool_name
            return

        decision.retry_tool = None
        decision.exhausted_options.add(tool_name)
        if self._remaining_options(decision):
            replay.active = self._restore(decision, replay)
            return

        self._backtrack(replay)

    def _record_success(
        self,
        replay: _ReplayState,
        tool_name: str,
    ) -> None:
        decision = replay.decisions[-1]
        decision.selected_option = tool_name
        decision.retry_tool = None

        replay.active = self._after_tool(
            replay.active,
            self.project.tool(tool_name),
        )
        replay.recovering = False
        replay.last_failed_tool = None
        replay.last_failure_reason = None
        replay.backtrack_depth = 0

        if replay.active.next_tools:
            self._push_decision(replay)

    def _backtrack(self, replay: _ReplayState) -> None:
        depth = 0

        while replay.decisions:
            exhausted_decision = replay.decisions.pop()
            depth += 1

            if not replay.decisions:
                replay.active = self._copy_state(
                    exhausted_decision.checkpoint
                )
                replay.active.available_artifacts.update(
                    replay.external_artifacts
                )
                replay.backtrack_depth = max(0, depth - 1)
                replay.blocked = True
                return

            parent = replay.decisions[-1]
            selected_branch = parent.selected_option
            if selected_branch is None:
                raise RuntimeError("Invalid recovery decision stack.")

            parent.exhausted_options.add(selected_branch)
            parent.selected_option = None
            parent.retry_tool = None
            replay.active = self._restore(parent, replay)

            if self._remaining_options(parent):
                replay.backtrack_depth = depth
                return

    def _reject_target_candidate(self, replay: _ReplayState) -> None:
        """Choosing a continuation means the current candidate is rejected."""
        if not self._targets_ready(replay.active):
            return

        target_names = set(self.project.target_artifacts)
        replay.active.produced_artifacts.difference_update(target_names)
        replay.active.targets_accepted = False

        if replay.decisions:
            replay.decisions[-1].checkpoint.produced_artifacts.difference_update(
                target_names
            )
            replay.decisions[-1].checkpoint.targets_accepted = False

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
            produced_artifacts.difference_update(
                self.project.target_artifacts
            )
        produced_artifacts.update(output_names)

        return _AdviceState(
            available_artifacts=available_artifacts,
            produced_artifacts=produced_artifacts,
            next_tools=self.project.workflow.following_tools(tool.name),
        )

    def _push_decision(self, replay: _ReplayState) -> None:
        if not replay.active.next_tools:
            return
        replay.decisions.append(
            _DecisionFrame(
                checkpoint=self._copy_state(replay.active),
                options=replay.active.next_tools,
            )
        )

    def _available_options(
        self,
        replay: _ReplayState,
    ) -> tuple[str, ...]:
        if replay.blocked or not replay.decisions:
            return ()

        decision = replay.decisions[-1]
        if decision.selected_option is not None:
            return ()
        if decision.retry_tool is not None:
            return (decision.retry_tool,)
        return self._remaining_options(decision)

    @staticmethod
    def _remaining_options(
        decision: _DecisionFrame,
    ) -> tuple[str, ...]:
        return tuple(
            tool_name
            for tool_name in decision.options
            if tool_name not in decision.exhausted_options
        )

    def _restore(
        self,
        decision: _DecisionFrame,
        replay: _ReplayState,
    ) -> _AdviceState:
        state = self._copy_state(decision.checkpoint)
        state.available_artifacts.update(replay.external_artifacts)
        return state

    @staticmethod
    def _copy_state(state: _AdviceState) -> _AdviceState:
        return _AdviceState(
            available_artifacts=set(state.available_artifacts),
            produced_artifacts=set(state.produced_artifacts),
            next_tools=state.next_tools,
            targets_accepted=state.targets_accepted,
        )

    def _tool_action(
        self,
        replay: _ReplayState,
        tool_name: str,
    ) -> Literal["RUN", "RETRY", "ALTERNATIVE"]:
        if not replay.recovering:
            return "RUN"
        decision = replay.decisions[-1]
        if decision.retry_tool == tool_name:
            return "RETRY"
        return "ALTERNATIVE"

    def _recovery_context(
        self,
        replay: _ReplayState,
    ) -> RecoveryContext:
        exhausted_options: tuple[str, ...] = ()
        if replay.decisions:
            decision = replay.decisions[-1]
            exhausted_options = tuple(
                tool_name
                for tool_name in decision.options
                if tool_name in decision.exhausted_options
            )
        return RecoveryContext(
            last_failed_tool=replay.last_failed_tool,
            last_failure_reason=replay.last_failure_reason,
            backtrack_depth=replay.backtrack_depth,
            exhausted_options=exhausted_options,
        )

    def _tool_option(
        self,
        tool_name: str,
        available_artifacts: set[str],
        action: Literal["RUN", "RETRY", "ALTERNATIVE"],
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
            action=action,
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

        continuation = self._copy_state(state)
        continuation.produced_artifacts.difference_update(
            self.project.target_artifacts
        )
        return bool(self._bootstrap_routes(continuation))

    def _is_complete(self, state: _AdviceState) -> bool:
        return self._targets_ready(state) and (
            not self._acceptance_required(state)
            or state.targets_accepted
        )
