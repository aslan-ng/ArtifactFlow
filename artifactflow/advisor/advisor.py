"""Directions for progressing through an artifact workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from artifactflow.project.log import (
    ArtifactAvailable,
    ProjectEvent,
    TargetsAccepted,
    ToolFailed,
    ToolSucceeded,
)
from artifactflow.project.project import Project
from artifactflow.tool.tool import Tool


ToolAction = Literal["RUN", "RETRY", "ALTERNATIVE"]
ToolOutcome = Literal[
    "CONTINUE",
    "TARGETS_READY",
    "COMPLETE",
    "DEAD_END",
]
CommandStatus = Literal["COMMAND", "RECOVERY", "COMPLETE", "BLOCKED"]


@dataclass(frozen=True, slots=True)
class ToolOption:
    """An executable root tool or a future tool shown in its preview.

    Only options directly inside ``AdvisorCommand.options`` are executable.
    Nested ``continuations`` show what may follow if their parent succeeds.
    """

    tool_name: str
    missing_artifacts: tuple[str, ...] = ()
    action: ToolAction = "RUN"
    continuations: tuple[ToolOption, ...] = ()
    outcome: ToolOutcome = "CONTINUE"
    has_more: bool = False
    options_truncated: bool = False


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

    status: CommandStatus
    options: tuple[ToolOption, ...] = ()
    options_truncated: bool = False
    target_artifacts: tuple[str, ...] = ()
    target_acceptance_required: bool = False
    recovery: RecoveryContext | None = None
    message: str = ""


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
    Record observed events and say what may happen next.

    ``advise`` is the single method intended for a future MCP tool. Root
    options are executable alternatives. Their nested continuations are
    success-assuming previews controlled by ``lookahead_depth`` and are not
    executable yet. ``max_options`` limits the visible breadth at each
    decision point.

    After a failure, the Advisor offers the retry first and then unchecked
    siblings when breadth permits. Two failures exhaust one option. Once the
    current decision is exhausted, recovery restores the nearest earlier
    decision with alternatives. A target candidate requires acceptance only
    when a continuation can produce a fresh candidate.
    """

    def __init__(
        self,
        project: Project,
        lookahead_depth: int = 1,
        max_options: int | None = None,
    ) -> None:
        if isinstance(lookahead_depth, bool) or not isinstance(
            lookahead_depth,
            int,
        ):
            raise TypeError("lookahead_depth must be an integer.")
        if lookahead_depth < 1:
            raise ValueError("lookahead_depth must be at least 1.")
        if max_options is not None:
            if isinstance(max_options, bool) or not isinstance(
                max_options,
                int,
            ):
                raise TypeError("max_options must be an integer or None.")
            if max_options < 1:
                raise ValueError("max_options must be at least 1 or None.")

        self.project = project
        self.lookahead_depth = lookahead_depth
        self.max_options = max_options
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

    def advise(
        self,
        report: ProjectEvent | None = None,
    ) -> AdvisorCommand:
        """Record one observed event, then return the current direction.

        Calling without a report is read-only. Tool reports are accepted only
        for visible root options; nested continuation previews cannot be
        executed directly.
        """
        replay = self._replay_log()

        if report is None:
            return self._build_command(replay)

        self._validate_report(report, replay)
        next_replay = self._replay_events((*self.project.events, report))
        command = self._build_command(next_replay)

        # Append only after validation and advice construction succeed.
        self.project.log.append(report)
        return command

    def _build_command(self, replay: _ReplayState) -> AdvisorCommand:
        """Build advice from one reconstructed project state."""
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

        eligible_tool_names = self._eligible_options(replay)
        if not eligible_tool_names:
            return AdvisorCommand(
                status="BLOCKED",
                message="No tool can continue the project.",
            )

        tool_names = self._limit_options(eligible_tool_names)
        status: Literal["COMMAND", "RECOVERY"] = (
            "RECOVERY"
            if replay.recovering
            else "COMMAND"
        )
        options = tuple(
            self._tool_option(
                tool_name,
                state,
                self._tool_action(replay, tool_name),
                self.lookahead_depth,
            )
            for tool_name in tool_names
        )

        if status == "RECOVERY":
            recovery = self._recovery_context(replay)
            if replay.backtrack_depth:
                message = (
                    "The current branch is exhausted. Choose an alternative "
                    "from the nearest earlier decision point."
                )
            else:
                message = (
                    "Choose a retry or another option from the current "
                    "decision point."
                )
        elif targets_ready:
            recovery = None
            message = (
                "The target artifacts are ready. Accept them if they meet "
                "the project conditions, or choose a tool to continue."
            )
        else:
            recovery = None
            message = (
                "Choose one root tool, obtain its missing artifacts, and run "
                "it once. Then report whether it succeeds or fails."
            )

        return AdvisorCommand(
            status=status,
            options=options,
            options_truncated=(
                len(tool_names) < len(eligible_tool_names)
            ),
            target_artifacts=(
                self.project.target_artifacts
                if targets_ready
                else ()
            ),
            target_acceptance_required=acceptance_required,
            recovery=recovery,
            message=message,
        )

    def _replay_log(self) -> _ReplayState:
        return self._replay_events(self.project.events)

    def _replay_events(
        self,
        events: tuple[ProjectEvent, ...],
    ) -> _ReplayState:
        """Reconstruct active advice state from ordered factual events."""
        initial_state = self._initial_state()
        replay = _ReplayState(
            active=initial_state,
            decisions=[],
            external_artifacts=set(),
        )
        self._push_decision(replay)

        for event in events:
            if self._is_complete(replay.active):
                raise ValueError(
                    "The project log contains work after completion."
                )
            if replay.blocked:
                raise ValueError(
                    "The project log contains work after it became blocked."
                )

            if not isinstance(
                event,
                (
                    ArtifactAvailable,
                    ToolSucceeded,
                    ToolFailed,
                    TargetsAccepted,
                ),
            ):
                raise TypeError("Advice reports must be project events.")

            if isinstance(event, ArtifactAvailable):
                self._record_external_artifact(replay, event.artifact_name)
                continue

            if isinstance(event, TargetsAccepted):
                if not (
                    self._targets_ready(replay.active)
                    and self._acceptance_required(replay.active)
                ):
                    raise ValueError(
                        "Target artifacts cannot be accepted before they "
                        "are produced or when no candidate is awaiting "
                        "acceptance."
                    )
                replay.active.targets_accepted = True
                continue

            allowed_tools = self._eligible_options(replay)
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

    def _validate_report(
        self,
        report: ProjectEvent,
        replay: _ReplayState,
    ) -> None:
        """Reject unsupported or hidden tool reports before logging them."""
        if not isinstance(
            report,
            (
                ArtifactAvailable,
                ToolSucceeded,
                ToolFailed,
                TargetsAccepted,
            ),
        ):
            raise TypeError("Advice reports must be project events.")

        if isinstance(report, (ToolSucceeded, ToolFailed)):
            visible_tools = self._visible_options(replay)
            if report.tool_name not in visible_tools:
                raise ValueError(
                    f"Tool {report.tool_name!r} was not a visible root "
                    "option."
                )

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
            return

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

    def _eligible_options(
        self,
        replay: _ReplayState,
    ) -> tuple[str, ...]:
        """Return every structurally valid root option in priority order."""
        if replay.blocked or not replay.decisions:
            return ()

        decision = replay.decisions[-1]
        if decision.selected_option is not None:
            return ()

        remaining = self._remaining_options(decision)
        if not replay.recovering:
            return remaining

        pending_retries = tuple(
            tool_name
            for tool_name in remaining
            if decision.failure_counts.get(tool_name, 0) == 1
        )
        untried = tuple(
            tool_name
            for tool_name in remaining
            if decision.failure_counts.get(tool_name, 0) == 0
        )
        latest_retry = (
            (replay.last_failed_tool,)
            if replay.last_failed_tool in pending_retries
            else ()
        )
        other_retries = tuple(
            tool_name
            for tool_name in pending_retries
            if tool_name != replay.last_failed_tool
        )
        return latest_retry + other_retries + untried

    def _visible_options(
        self,
        replay: _ReplayState,
    ) -> tuple[str, ...]:
        """Return the eligible roots exposed by the breadth setting."""
        return self._limit_options(self._eligible_options(replay))

    def _limit_options(
        self,
        tool_names: tuple[str, ...],
    ) -> tuple[str, ...]:
        if self.max_options is None:
            return tool_names
        return tool_names[:self.max_options]

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
    ) -> ToolAction:
        if not replay.recovering:
            return "RUN"
        decision = replay.decisions[-1]
        if decision.failure_counts.get(tool_name, 0) == 1:
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
        state: _AdviceState,
        action: ToolAction,
        depth: int,
    ) -> ToolOption:
        tool = self.project.tool(tool_name)
        input_artifacts = tuple(
            artifact.name
            for artifact in tool.inputs
        )
        next_state = self._after_tool(state, tool)
        targets_ready = self._targets_ready(next_state)

        if targets_ready and self._acceptance_required(next_state):
            outcome: ToolOutcome = "TARGETS_READY"
        elif targets_ready:
            outcome = "COMPLETE"
        elif not next_state.next_tools:
            outcome = "DEAD_END"
        else:
            outcome = "CONTINUE"

        can_continue = (
            outcome in ("CONTINUE", "TARGETS_READY")
            and bool(next_state.next_tools)
        )
        continuations: tuple[ToolOption, ...] = ()
        options_truncated = False
        has_more = can_continue and depth == 1

        if can_continue and depth > 1:
            next_tool_names = self._limit_options(next_state.next_tools)
            options_truncated = (
                len(next_tool_names) < len(next_state.next_tools)
            )
            continuations = tuple(
                self._tool_option(
                    next_tool_name,
                    next_state,
                    "RUN",
                    depth - 1,
                )
                for next_tool_name in next_tool_names
            )

        return ToolOption(
            tool_name=tool.name,
            missing_artifacts=tuple(
                artifact_name
                for artifact_name in input_artifacts
                if artifact_name not in state.available_artifacts
            ),
            action=action,
            continuations=continuations,
            outcome=outcome,
            has_more=has_more,
            options_truncated=options_truncated,
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
