"""Directions for progressing through an artifact workflow."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field, replace
from typing import Literal

import networkx as nx

from artifactflow.advisor.history import (
    AdvisedOption,
    AdviceHistory,
    AdviceSnapshot,
)
from artifactflow.advisor.policy import (
    CandidateScope,
    CandidateTransition,
    GuidancePolicy,
    WORKFLOW_ADHERENT,
)
from artifactflow.plan.plan import Plan, PlanRouteKey
from artifactflow.project.log import (
    ArtifactAvailable,
    ArtifactVersion,
    ProjectEvent,
    TargetsAccepted,
    ToolFailed,
    ToolSucceeded,
)
from artifactflow.project.project import ActionLocation, Project
from artifactflow.tool.tool import Tool


ToolAction = Literal["RUN", "RETRY", "ALTERNATIVE"]
CycleAction = Literal["REPEAT", "EXIT", "EXIT_PREPARATION"]
ToolOutcome = Literal[
    "CONTINUE",
    "TARGETS_READY",
    "COMPLETE",
    "DEAD_END",
]
CommandStatus = Literal["COMMAND", "COMPLETE", "BLOCKED"]


@dataclass(frozen=True, slots=True)
class ToolOption:
    """An executable root tool or a future tool shown in its preview.

    Only options directly inside ``AdvisorCommand.options`` are executable.
    Nested ``continuations`` show what may follow if their parent succeeds.
    """

    tool_name: str
    missing_artifacts: tuple[str, ...] = ()
    input_artifacts: tuple[tuple[str, int], ...] = ()
    action: ToolAction = "RUN"
    continuations: tuple[ToolOption, ...] = ()
    outcome: ToolOutcome = "CONTINUE"
    has_more: bool = False
    options_truncated: bool = False
    scope: Literal[
        "PROPOSED_PLAN",
        "WORKFLOW_PLAN",
        "TOOL_NETWORK",
    ] = "PROPOSED_PLAN"
    transition: Literal[
        "CONTINUE_CURRENT",
        "REJOIN",
        "RESTORE_CHECKPOINT",
    ] = "CONTINUE_CURRENT"
    supporting_plans: tuple[tuple[str, ...], ...] = ()
    cycle_action: CycleAction | None = None
    supporting_route_keys: tuple[PlanRouteKey, ...] = ()


@dataclass(frozen=True, slots=True)
class DeviationContext:
    """The latest observed tool call that did not follow visible advice."""

    observed_tool: str
    location: ActionLocation
    proposed_options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdvisorCommand:
    """One self-contained direction returned by the Advisor."""

    status: CommandStatus
    options: tuple[ToolOption, ...] = ()
    options_truncated: bool = False
    target_artifacts: tuple[str, ...] = ()
    target_acceptance_required: bool = False
    deviation: DeviationContext | None = None
    message: str = ""


@dataclass(slots=True)
class _AdviceState:
    """Active artifacts and tools at one point along the selected route."""

    available_artifacts: set[str]
    active_artifacts: dict[str, ArtifactVersion]
    active_producers: dict[str, str | None]
    produced_artifacts: set[str]
    target_candidates: dict[str, ArtifactVersion]
    next_tools: tuple[str, ...]
    route_keys: tuple[PlanRouteKey, ...] = ()
    completed_tools: tuple[str, ...] = ()
    last_tool: str | None = None
    targets_accepted: bool = False


@dataclass(slots=True)
class _DecisionFrame:
    """A restorable tool choice encountered along the active route."""

    checkpoint: _AdviceState
    options: tuple[str, ...]
    exhausted_options: set[str] = field(default_factory=set)
    failure_counts: dict[str, int] = field(default_factory=dict)
    selected_option: str | None = None


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One policy-neutral way to issue the next concrete tool command."""

    tool_name: str
    scope: CandidateScope
    transition: CandidateTransition
    supporting_plans: tuple[Plan, ...] = ()
    decision_index: int | None = None
    remaining_tools: int = 0
    stable_order: int = 0
    cycle_action: CycleAction | None = None
    cycle_gate: tuple[str, ...] | None = None


@dataclass(slots=True)
class _ReplayState:
    """State reconstructed from the complete project event log."""

    active: _AdviceState
    decisions: list[_DecisionFrame]
    external_artifacts: dict[str, ArtifactVersion]
    artifact_producers: dict[tuple[str, int], str | None]
    recovering: bool = False
    last_failed_tool: str | None = None
    blocked: bool = False
    proposed_route_keys: tuple[PlanRouteKey, ...] = ()
    last_deviation: DeviationContext | None = None
    deviating: bool = False
    last_observed_tool: str | None = None


class Advisor:
    """
    Read observed execution events and say what may happen next.

    ``advise`` is the single method intended for a future MCP tool. Root
    options are executable alternatives. Their nested continuations are
    success-assuming previews controlled by ``lookahead_depth`` and are not
    executable yet. ``max_options`` limits the visible breadth at each
    decision point, except that an active cycle's repeat/exit pair is kept as
    one atomic control decision even when the configured limit is one.

    When retry allowance remains after a failure, the Advisor offers that
    retry first and then unchecked siblings when breadth permits.
    ``max_retries`` controls how many retries an option receives at one
    decision visit. Once the current decision is exhausted, the nearest
    earlier decision with alternatives is restored. A target candidate
    requires acceptance only when a continuation can produce a fresh
    candidate. At an entered optimization-cycle gate, repeating is preferred
    while its exit remains visible and selectable. ``policy`` accepts a
    :class:`GuidancePolicy`; its ``workflow_adherence`` may be any number
    from 0.0 through 1.0, not only one of the named presets.
    """

    def __init__(
        self,
        project: Project,
        *,
        lookahead_depth: int = 1,
        max_options: int | None = None,
        policy: GuidancePolicy = WORKFLOW_ADHERENT,
        advice_history: AdviceHistory | None = None,
        max_retries: int = 1,
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
        if isinstance(max_retries, bool) or not isinstance(max_retries, int):
            raise TypeError("max_retries must be an integer.")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        if not isinstance(policy, GuidancePolicy):
            raise TypeError("policy must be a GuidancePolicy.")
        if advice_history is not None and not isinstance(
            advice_history,
            AdviceHistory,
        ):
            raise TypeError("advice_history must be an AdviceHistory or None.")

        self.project = project
        self.lookahead_depth = lookahead_depth
        self.max_options = max_options
        self._max_retries = max_retries
        self.policy = policy
        self.advice_history = (
            advice_history
            if advice_history is not None
            else AdviceHistory()
        )
        self._tool_positions = {
            tool.name: position
            for position, tool in enumerate(project.tool_network.tools)
        }

        self.plans = tuple(
            project.workflow.discover_plans(
                project.starting_artifacts,
                project.target_artifacts,
            )
        )
        if not self.plans:
            raise ValueError(
                "The workflow has no route from its starting artifacts "
                "to all target artifacts."
            )
        self._plans_by_route_key = {
            self._plan_route_key(plan): plan
            for plan in self.plans
        }
        self._plans_by_signature: dict[tuple[str, ...], tuple[Plan, ...]] = {}
        for plan in self.plans:
            signature = self._plan_signature(plan)
            self._plans_by_signature[signature] = (
                *self._plans_by_signature.get(signature, ()),
                plan,
            )

        routes = tuple(
            plan.input_requirements().initial_artifacts
            for plan in self.plans
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

    @property
    def max_retries(self) -> int:
        """Return the fixed retry allowance for each option visit."""
        return self._max_retries

    @property
    def _configuration(self) -> Hashable:
        """Return the settings that make one advice snapshot reproducible."""
        return (
            self.lookahead_depth,
            self.max_options,
            self.max_retries,
            self.policy.workflow_adherence,
        )

    def advise(self) -> AdvisorCommand:
        """Return current advice reconstructed from the execution log.

        A runtime observer, raw-log adapter, or simulation records activity on
        the Project separately. The execution log remains factual; this method
        only records a compact snapshot of the directions it actually showed.
        Therefore several tool calls may occur between consultations without
        breaking the connection to the Advisor.
        """
        command = self._build_command(self._replay_log())
        self.advice_history.record(
            event_position=len(self.project.events),
            configuration=self._configuration,
            options=(
                AdvisedOption(
                    tool_name=option.tool_name,
                    input_artifacts=option.input_artifacts,
                    supporting_plan_signatures=option.supporting_plans,
                    supporting_route_keys=option.supporting_route_keys,
                )
                for option in command.options
            ),
        )
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
                deviation=replay.last_deviation,
                message="The project is complete.",
            )

        if replay.blocked:
            return AdvisorCommand(
                status="BLOCKED",
                deviation=replay.last_deviation,
                message=(
                    "Every tool option and its allowed retries have been "
                    "exhausted. "
                    "The project is blocked."
                ),
            )

        candidates = self._candidate_options(replay)
        if not candidates:
            return AdvisorCommand(
                status="BLOCKED",
                deviation=replay.last_deviation,
                message="No tool can continue the project.",
            )

        visible_candidates = self._limit_candidates(candidates)
        options = tuple(
            self._tool_option(
                candidate.tool_name,
                self._candidate_state(replay, candidate),
                self._candidate_action(replay, candidate),
                self.lookahead_depth,
                candidate=candidate,
            )
            for candidate in visible_candidates
        )

        if replay.last_deviation is not None:
            message = (
                "The observed tool differed from the visible advice. Choose "
                "whether to continue that direction, rejoin a Plan, or "
                "restore an earlier decision."
            )
        elif targets_ready:
            message = (
                "The target artifacts are ready. Accept them if they meet "
                "the project conditions, or choose a tool to continue."
            )
        else:
            message = (
                "Choose one root tool, obtain its missing artifacts, and run "
                "it once. Ask for advice again after its result is recorded."
            )

        return AdvisorCommand(
            status="COMMAND",
            options=options,
            options_truncated=(
                len(visible_candidates) < len(candidates)
            ),
            target_artifacts=(
                self.project.target_artifacts
                if targets_ready
                else ()
            ),
            target_acceptance_required=acceptance_required,
            deviation=replay.last_deviation,
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
            external_artifacts={},
            artifact_producers={},
        )
        self._push_decision(replay)

        active_snapshot: AdviceSnapshot | None = None
        snapshot_consumed = False

        for event_position, event in enumerate(events):
            snapshot = self.advice_history.latest_before(
                event_position + 1,
            )
            if snapshot is not active_snapshot:
                active_snapshot = snapshot
                snapshot_consumed = False

            if not isinstance(
                event,
                (
                    ArtifactAvailable,
                    ToolSucceeded,
                    ToolFailed,
                    TargetsAccepted,
                ),
            ):
                raise TypeError("The execution log contains an invalid event.")

            if self._state_is_complete(replay.active):
                if isinstance(event, (ToolSucceeded, ToolFailed)):
                    self._validate_tool_event(event)
                    proposed_plans = self._plans_for_route_keys(
                        replay.proposed_route_keys
                    )
                    replay.last_deviation = DeviationContext(
                        observed_tool=event.tool_name,
                        location=self.project.classify_action(
                            event.tool_name,
                            proposed_plans,
                        ),
                        proposed_options=(),
                    )
                    replay.last_observed_tool = event.tool_name
                # The canonical log still retains the observation, but a
                # terminal Project is not silently reopened by later work.
                continue

            if isinstance(event, ArtifactAvailable):
                self._record_external_artifact(replay, event.artifact)
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
                if event.targets:
                    active_targets = tuple(
                        replay.active.target_candidates[name]
                        for name in self.project.target_artifacts
                    )
                    if event.targets != active_targets:
                        raise ValueError(
                            "Target acceptance does not reference the active "
                            "target versions."
                        )
                replay.active.targets_accepted = True
                continue

            self._validate_tool_event(event)

            candidates = self._candidate_options(replay)
            candidate = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.tool_name == event.tool_name
                    and self._event_matches_candidate_inputs(
                        replay,
                        candidate,
                        event,
                    )
                ),
                None,
            )
            visible_options = (
                active_snapshot.visible_root_tools
                if active_snapshot is not None and not snapshot_consumed
                else ()
            )
            proposed_plans = self._proposed_plans_for_event(
                replay,
                active_snapshot,
                event,
                snapshot_consumed,
            )
            if proposed_plans:
                replay.proposed_route_keys = tuple(
                    self._plan_route_key(plan)
                    for plan in proposed_plans
                )

            followed_visible_advice = (
                active_snapshot is None
                or snapshot_consumed
                or self._snapshot_contains_event(active_snapshot, event)
            )
            followed_active_plan = (
                candidate is not None
                and (
                    self._snapshot_contains_event(active_snapshot, event)
                    or not replay.proposed_route_keys
                    or candidate.scope is CandidateScope.PROPOSED_PLAN
                )
            )
            deviated = not (
                followed_visible_advice
                and followed_active_plan
            )
            if active_snapshot is None and candidate is not None:
                deviated = False

            if deviated:
                location = self.project.classify_action(
                    event.tool_name,
                    proposed_plans,
                )
                replay.last_deviation = DeviationContext(
                    observed_tool=event.tool_name,
                    location=location,
                    proposed_options=visible_options,
                )
                replay.deviating = True
            elif candidate is not None and candidate.supporting_plans:
                replay.proposed_route_keys = tuple(
                    self._plan_route_key(plan)
                    for plan in candidate.supporting_plans
                )

            snapshot_consumed = True

            if candidate is not None:
                # Visibility determines whether this was a deviation, but the
                # exact candidate still determines which checkpoint and input
                # versions the observed call actually used.
                self._activate_candidate(replay, candidate)
            elif deviated:
                self._prepare_unadvised_tool(
                    replay,
                    event.tool_name,
                    force_child=True,
                )
            else:
                self._prepare_unadvised_tool(replay, event.tool_name)

            self._activate_event_inputs(replay, event.inputs)
            self._reject_target_candidate(replay)

            if isinstance(event, ToolFailed):
                self._record_failure(replay, event)
            elif isinstance(event, ToolSucceeded):
                self._record_success(
                    replay,
                    event,
                    candidate=candidate,
                    use_tool_network=(
                        deviated
                        or not self.project.workflow.contains_tool(
                            event.tool_name
                        )
                    ),
                )
                if (
                    not deviated
                    and candidate is not None
                    and candidate.transition in (
                        CandidateTransition.REJOIN,
                        CandidateTransition.RESTORE_CHECKPOINT,
                    )
                ):
                    replay.deviating = False
                    replay.last_deviation = None
            replay.last_observed_tool = event.tool_name

        return replay

    def _record_external_artifact(
        self,
        replay: _ReplayState,
        artifact: ArtifactVersion,
    ) -> None:
        artifact_name = artifact.artifact_name
        if artifact_name not in self.project.tool_network.artifact_names:
            raise ValueError(f"Unknown artifact: {artifact_name!r}")

        replay.external_artifacts[artifact_name] = artifact
        replay.artifact_producers[
            (artifact_name, artifact.version)
        ] = None
        replay.active.available_artifacts.add(artifact_name)
        replay.active.active_artifacts[artifact_name] = artifact
        replay.active.active_producers[artifact_name] = None
        for decision in replay.decisions:
            decision.checkpoint.available_artifacts.add(artifact_name)
            decision.checkpoint.active_artifacts[artifact_name] = artifact
            decision.checkpoint.active_producers[artifact_name] = None

    @staticmethod
    def _activate_event_inputs(
        replay: _ReplayState,
        inputs: tuple[ArtifactVersion, ...],
    ) -> None:
        """Bind one observed call to the exact artifact versions it used.

        Unlike an externally supplied artifact, an older input chosen for one
        call changes only that active attempt and its retry checkpoint. It
        must not replace newer bindings in unrelated recovery checkpoints.
        """
        for artifact in inputs:
            artifact_name = artifact.artifact_name
            replay.active.available_artifacts.add(artifact_name)
            replay.active.active_artifacts[artifact_name] = artifact
            replay.active.active_producers[artifact_name] = (
                replay.artifact_producers[
                    (artifact_name, artifact.version)
                ]
            )

        if replay.decisions:
            checkpoint = replay.decisions[-1].checkpoint
            for artifact in inputs:
                artifact_name = artifact.artifact_name
                checkpoint.available_artifacts.add(artifact_name)
                checkpoint.active_artifacts[artifact_name] = artifact
                checkpoint.active_producers[artifact_name] = (
                    replay.artifact_producers[
                        (artifact_name, artifact.version)
                    ]
                )

    def _validate_tool_event(
        self,
        event: ToolSucceeded | ToolFailed,
    ) -> None:
        """Check that observed artifact roles match the workflow schema."""
        tool = self.project.tool(event.tool_name)
        expected_inputs = {
            artifact.name
            for artifact in tool.inputs
        }
        actual_inputs = {
            artifact.artifact_name
            for artifact in event.inputs
        }
        if expected_inputs != actual_inputs:
            raise ValueError(
                f"Observed tool {tool.name!r} used artifacts "
                f"{sorted(actual_inputs)}, but the workflow declares "
                f"{sorted(expected_inputs)}."
            )

        if isinstance(event, ToolSucceeded):
            expected_outputs = {
                artifact.name
                for artifact in tool.outputs
            }
            actual_outputs = {
                artifact.artifact_name
                for artifact in event.outputs
            }
            if expected_outputs != actual_outputs:
                raise ValueError(
                    f"Observed tool {tool.name!r} created artifacts "
                    f"{sorted(actual_outputs)}, but the workflow declares "
                    f"{sorted(expected_outputs)}."
                )

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

        if self._can_retry(failure_count):
            return

        decision.exhausted_options.add(tool_name)
        if self._remaining_options(decision):
            replay.active = self._restore(decision, replay)
            return

        self._backtrack(replay)

    def _can_retry(self, failure_count: int) -> bool:
        """Return whether one more attempt is allowed after these failures."""
        return 0 < failure_count <= self.max_retries

    def _record_success(
        self,
        replay: _ReplayState,
        event: ToolSucceeded,
        *,
        candidate: _Candidate | None = None,
        use_tool_network: bool = False,
    ) -> None:
        tool_name = event.tool_name
        if not replay.decisions:
            self._prepare_unadvised_tool(replay, tool_name)
        decision = replay.decisions[-1]
        decision.selected_option = tool_name

        replay.active = self._after_tool(
            replay.active,
            self.project.tool(tool_name),
            event.outputs,
            use_tool_network=use_tool_network,
            supporting_plans=(
                candidate.supporting_plans
                if candidate is not None
                else ()
            ),
        )
        for artifact in event.outputs:
            replay.artifact_producers[
                (artifact.artifact_name, artifact.version)
            ] = tool_name
        replay.recovering = False
        replay.last_failed_tool = None

        if replay.active.next_tools:
            self._push_decision(replay)
        elif (
            not self._targets_ready(replay.active)
            and not use_tool_network
        ):
            self._backtrack(replay)

    def _backtrack(self, replay: _ReplayState) -> None:
        while replay.decisions:
            exhausted_decision = replay.decisions.pop()

            if not replay.decisions:
                replay.active = self._copy_state(
                    exhausted_decision.checkpoint
                )
                replay.active.available_artifacts.update(
                    replay.external_artifacts
                )
                replay.active.active_artifacts.update(
                    replay.external_artifacts
                )
                replay.active.active_producers.update(
                    (artifact_name, None)
                    for artifact_name in replay.external_artifacts
                )
                replay.blocked = True
                return

            parent = replay.decisions[-1]
            selected_branch = parent.selected_option
            if selected_branch is None:
                raise RuntimeError("Invalid recovery decision stack.")

            # The same tool can appear in consecutive frontiers when several
            # independent prerequisites belong to one Plan. Do not give an
            # exhausted prerequisite a fresh retry merely because an earlier
            # frame also displayed it.
            parent.exhausted_options.update(
                set(parent.options) & exhausted_decision.exhausted_options
            )
            parent.exhausted_options.add(selected_branch)
            parent.selected_option = None
            replay.active = self._restore(parent, replay)

            if self._remaining_options(parent):
                return

    def _reject_target_candidate(self, replay: _ReplayState) -> None:
        """Choosing a continuation means the current candidate is rejected."""
        if not self._targets_ready(replay.active):
            return

        renewable_targets = set(self._renewable_targets(replay.active))
        replay.active.produced_artifacts.difference_update(renewable_targets)
        for target_name in renewable_targets:
            replay.active.target_candidates.pop(target_name, None)
        replay.active.targets_accepted = False

        if replay.decisions:
            replay.decisions[-1].checkpoint.produced_artifacts.difference_update(
                renewable_targets
            )
            for target_name in renewable_targets:
                replay.decisions[-1].checkpoint.target_candidates.pop(
                    target_name,
                    None,
                )
            replay.decisions[-1].checkpoint.targets_accepted = False

    def _initial_state(self) -> _AdviceState:
        state = _AdviceState(
            available_artifacts=set(),
            active_artifacts={},
            active_producers={},
            produced_artifacts=set(),
            target_candidates={},
            next_tools=(),
            route_keys=tuple(
                self._plan_route_key(plan)
                for plan in self.plans
            ),
        )
        state.next_tools = self._plan_frontier(state, self.plans)
        return state

    def _after_tool(
        self,
        state: _AdviceState,
        tool: Tool,
        output_versions: tuple[ArtifactVersion, ...] = (),
        *,
        use_tool_network: bool = False,
        supporting_plans: tuple[Plan, ...] = (),
    ) -> _AdviceState:
        input_names = {artifact.name for artifact in tool.inputs}
        output_names = {artifact.name for artifact in tool.outputs}

        available_artifacts = set(state.available_artifacts)
        available_artifacts.update(input_names)
        available_artifacts.update(output_names)

        active_artifacts = dict(state.active_artifacts)
        active_artifacts.update(
            {
                artifact.artifact_name: artifact
                for artifact in output_versions
            }
        )
        active_producers = dict(state.active_producers)
        active_producers.update(
            (artifact_name, tool.name)
            for artifact_name in output_names
        )

        produced_artifacts = set(state.produced_artifacts)
        target_candidates = dict(state.target_candidates)
        produced_artifacts.update(output_names)
        for artifact in output_versions:
            if artifact.artifact_name in self.project.target_artifacts:
                target_candidates[artifact.artifact_name] = artifact

        if not supporting_plans:
            active_route_keys = set(state.route_keys)
            eligible_plans = tuple(
                plan
                for route_key, plan in self._plans_by_route_key.items()
                if (
                    not active_route_keys
                    or route_key in active_route_keys
                )
            )
            supporting_plans = self._frontier_plans(
                state,
                eligible_plans,
                tool.name,
            )

        next_state = _AdviceState(
            available_artifacts=available_artifacts,
            active_artifacts=active_artifacts,
            active_producers=active_producers,
            produced_artifacts=produced_artifacts,
            target_candidates=target_candidates,
            next_tools=(),
            route_keys=tuple(dict.fromkeys(
                self._plan_route_key(plan)
                for plan in supporting_plans
            )),
            completed_tools=(*state.completed_tools, tool.name),
            last_tool=tool.name,
        )
        next_state.next_tools = (
            self._plan_frontier(next_state, supporting_plans)
            if supporting_plans
            else self._following_tools(
                tool.name,
                use_tool_network=use_tool_network,
            )
        )
        return next_state

    def _following_tools(
        self,
        tool_name: str,
        *,
        use_tool_network: bool,
    ) -> tuple[str, ...]:
        network = (
            self.project.tool_network
            if use_tool_network
            else self.project.workflow
        )
        if not network.contains_tool(tool_name):
            network = self.project.tool_network

        tool = self.project.tool(tool_name)
        output_names = {
            artifact.name
            for artifact in tool.outputs
        }
        return tuple(
            candidate.name
            for candidate in network.tools
            if any(
                artifact.name in output_names
                for artifact in candidate.inputs
            )
        )

    def _plan_frontier(
        self,
        state: _AdviceState,
        plans: Iterable[Plan],
    ) -> tuple[str, ...]:
        """Return tools that can advance at least one active Plan.

        Independent roots in the same Plan remain available until they have
        all run, which makes joins work. A downstream tool waits for its
        internal producers; only external inputs and selected cycle seeds may
        be missing. After a choice inside a cycle, adjacency prevents skipping
        directly over the next required cycle step.
        """
        completed = set(state.completed_tools)
        available = state.available_artifacts
        frontier: set[str] = set()

        for plan in plans:
            tool_graph = plan.to_tool_dependency_graph()
            last_tool = (
                state.last_tool
                if state.last_tool in plan.tool_names
                else None
            )
            direct_successors = (
                set(tool_graph.successors(last_tool))
                if last_tool is not None
                else set()
            )
            bootstrap = plan.input_requirements().bootstrap_artifacts

            for tool in plan.tools:
                if tool.name in completed:
                    if (
                        last_tool is None
                        or tool.name not in direct_successors
                    ):
                        continue
                elif (
                    last_tool is not None
                    and tool.name not in direct_successors
                ):
                    if (
                        self._targets_ready(state)
                        or nx.has_path(tool_graph, last_tool, tool.name)
                    ):
                        # A downstream tool cannot skip its intermediate Plan
                        # steps. Once targets are ready, old ancestors also do
                        # not reopen a completed route.
                        continue
                    if (
                        nx.has_path(tool_graph, tool.name, last_tool)
                        and all(
                            output.name in available
                            for output in tool.outputs
                        )
                    ):
                        # An out-of-order call may leave an ancestor useful
                        # when it can still create a missing downstream input.
                        # Do not repeat ancestors whose outputs already exist.
                        continue

                blocked = False
                for artifact in tool.inputs:
                    if plan.has_explicit_producers:
                        producers = set(plan.producers_for_input(
                            tool.name,
                            artifact.name,
                        ))
                        if not producers:
                            # External inputs may be missing; the option owns
                            # the requirement and reports it to the caller.
                            continue
                        if (
                            state.active_producers.get(
                                artifact.name
                            ) in producers
                            or (
                                artifact.name in bootstrap
                                and plan.is_feedback_input(
                                    tool.name,
                                    artifact.name,
                                )
                            )
                        ):
                            continue
                        blocked = True
                        break

                    if artifact.name in available:
                        continue
                    producers = {
                        producer.name
                        for producer in plan.tools
                        if any(
                            output.name == artifact.name
                            for output in producer.outputs
                        )
                    }
                    if producers and artifact.name not in bootstrap:
                        blocked = True
                        break
                if not blocked:
                    frontier.add(tool.name)

        return tuple(
            tool.name
            for tool in self.project.tool_network.tools
            if tool.name in frontier
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

    def _candidate_options(
        self,
        replay: _ReplayState,
    ) -> tuple[_Candidate, ...]:
        """Build, merge, and rank valid next commands.

        The current decision supplies continuations from the observed state.
        While handling a deviation, restorable alternatives from earlier
        decisions are added as separate candidate variants. Candidates with
        the same concrete next tool are merged before breadth is limited.
        """
        if replay.blocked and not replay.deviating:
            return ()

        variants: list[_Candidate] = []
        current_names = self._eligible_options(replay)
        for order, tool_name in enumerate(current_names):
            variants.append(
                self._make_candidate(
                    replay,
                    tool_name,
                    CandidateTransition.CONTINUE_CURRENT,
                    decision_index=(
                        len(replay.decisions) - 1
                        if replay.decisions
                        else None
                    ),
                    stable_order=order,
                )
            )

        if replay.deviating:
            offset = len(variants)
            for decision_index in range(
                len(replay.decisions) - 2,
                -1,
                -1,
            ):
                decision = replay.decisions[decision_index]
                for tool_name in self._remaining_options(decision):
                    if tool_name == decision.selected_option:
                        continue
                    variants.append(
                        self._make_candidate(
                            replay,
                            tool_name,
                            CandidateTransition.RESTORE_CHECKPOINT,
                            decision_index=decision_index,
                            stable_order=offset + len(variants),
                        )
                    )

        # A deviation can enter a part of the ToolNetwork that the Workflow
        # does not describe. Discover its bounded, target-reaching structural
        # continuations and retain their Plan provenance on the root options.
        continuation_plans = self._network_continuation_plans(replay)
        for plan in continuation_plans:
            for tool_name in self._plan_roots(plan, replay.active):
                variants.append(
                    self._make_candidate(
                        replay,
                        tool_name,
                        CandidateTransition.CONTINUE_CURRENT,
                        decision_index=None,
                        supporting_plans=(plan,),
                        stable_order=len(variants),
                    )
                )

        merged: dict[
            tuple[str, tuple[tuple[str, int], ...]],
            _Candidate,
        ] = {}
        for candidate in variants:
            identity = (
                candidate.tool_name,
                self._candidate_input_artifacts(replay, candidate),
            )
            previous = merged.get(identity)
            if previous is None:
                merged[identity] = candidate
                continue

            previous_key = self._candidate_rank(replay, previous)
            candidate_key = self._candidate_rank(replay, candidate)
            preferred = (
                candidate
                if candidate_key < previous_key
                else previous
            )
            supporting_plans = tuple(dict(
                (
                    self._plan_route_key(plan),
                    plan,
                )
                for plan in (
                    *previous.supporting_plans,
                    *candidate.supporting_plans,
                )
            ).values())
            merged[identity] = _Candidate(
                tool_name=preferred.tool_name,
                scope=preferred.scope,
                transition=preferred.transition,
                supporting_plans=supporting_plans,
                decision_index=preferred.decision_index,
                remaining_tools=min(
                    previous.remaining_tools,
                    candidate.remaining_tools,
                ),
                stable_order=min(
                    previous.stable_order,
                    candidate.stable_order,
                ),
                cycle_action=preferred.cycle_action,
            )

        valid_candidates = tuple(
            candidate
            for candidate in merged.values()
            if self._candidate_reaches_useful_scope(replay, candidate)
        )
        valid_candidates = self._mark_cycle_gate_candidates(
            replay.active,
            valid_candidates,
        )
        return tuple(sorted(
            valid_candidates,
            key=lambda candidate: self._candidate_rank(replay, candidate),
        ))

    def _candidate_reaches_useful_scope(
        self,
        replay: _ReplayState,
        candidate: _Candidate,
    ) -> bool:
        if candidate.supporting_plans:
            return True
        if replay.decisions and candidate.decision_index is not None:
            decision = replay.decisions[candidate.decision_index]
            return self._can_retry(
                decision.failure_counts.get(candidate.tool_name, 0)
            )
        return (
            not replay.deviating
            and candidate.scope is not CandidateScope.TOOL_NETWORK
        )

    def _make_candidate(
        self,
        replay: _ReplayState,
        tool_name: str,
        transition: CandidateTransition,
        *,
        decision_index: int | None,
        supporting_plans: tuple[Plan, ...] | None = None,
        stable_order: int = 0,
    ) -> _Candidate:
        candidate_state = replay.active
        if (
            decision_index is not None
            and decision_index < len(replay.decisions) - 1
        ):
            candidate_state = self._restore(
                replay.decisions[decision_index],
                replay,
            )
        if supporting_plans is None:
            active_route_keys = set(candidate_state.route_keys)
            active_plans = tuple(
                plan
                for route_key, plan in self._plans_by_route_key.items()
                if (
                    not active_route_keys
                    or route_key in active_route_keys
                )
            )
            plans = self._frontier_plans(
                candidate_state,
                active_plans,
                tool_name,
            )
        else:
            plans = supporting_plans
        proposed_route_keys = set(replay.proposed_route_keys)
        proposed_plans = tuple(
            plan
            for plan in plans
            if self._plan_route_key(plan) in proposed_route_keys
        )
        if proposed_plans:
            scope = CandidateScope.PROPOSED_PLAN
            plans = proposed_plans
        elif (
            not proposed_route_keys
            and not replay.deviating
            and transition is CandidateTransition.CONTINUE_CURRENT
            and self.project.workflow.contains_tool(tool_name)
        ):
            # Before any advice is issued, the valid Workflow candidates are
            # precisely the Plans this command is about to propose.
            scope = CandidateScope.PROPOSED_PLAN
        elif self.project.workflow.contains_tool(tool_name):
            scope = CandidateScope.WORKFLOW_PLAN
        else:
            scope = CandidateScope.TOOL_NETWORK

        if (
            replay.deviating
            and transition is CandidateTransition.CONTINUE_CURRENT
            and scope is CandidateScope.PROPOSED_PLAN
        ):
            transition = CandidateTransition.REJOIN

        remaining_tools = min(
            (
                len(
                    set(plan.tool_names)
                    - set(candidate_state.completed_tools)
                )
                for plan in plans
            ),
            default=len(self.project.tool_network.tools),
        )
        return _Candidate(
            tool_name=tool_name,
            scope=scope,
            transition=transition,
            supporting_plans=plans,
            decision_index=decision_index,
            remaining_tools=remaining_tools,
            stable_order=(
                self._tool_positions.get(tool_name, len(self._tool_positions))
                + stable_order * (len(self._tool_positions) + 1)
            ),
        )

    def _candidate_rank(
        self,
        replay: _ReplayState,
        candidate: _Candidate,
    ) -> tuple[int, int, float, int, int, int]:
        state = self._candidate_state(replay, candidate)
        missing = len(self._missing_inputs(candidate.tool_name, state))
        retry_tier = 1
        if replay.recovering and replay.decisions:
            decision = replay.decisions[-1]
            if (
                candidate.decision_index == len(replay.decisions) - 1
                and self._can_retry(
                    decision.failure_counts.get(candidate.tool_name, 0)
                )
            ):
                retry_tier = 0
        policy_rank = self.policy.rank(
            candidate.scope,
            candidate.transition,
            missing_artifacts=missing,
            remaining_tools=candidate.remaining_tools,
            stable_order=candidate.stable_order,
        )
        cost, missing_count, remaining_tools, stable_order = policy_rank
        return (
            retry_tier,
            0 if candidate.cycle_action == "REPEAT" else 1,
            cost,
            missing_count,
            remaining_tools,
            stable_order,
        )

    def _preview_candidate_rank(
        self,
        state: _AdviceState,
        candidate: _Candidate,
    ) -> tuple[int, float, int, int, int]:
        policy_rank = self.policy.rank(
            candidate.scope,
            candidate.transition,
            missing_artifacts=len(
                self._missing_inputs(candidate.tool_name, state)
            ),
            remaining_tools=candidate.remaining_tools,
            stable_order=candidate.stable_order,
        )
        cost, missing_count, remaining_tools, stable_order = policy_rank
        return (
            0 if candidate.cycle_action == "REPEAT" else 1,
            cost,
            missing_count,
            remaining_tools,
            stable_order,
        )

    def _limit_candidates(
        self,
        candidates: tuple[_Candidate, ...],
    ) -> tuple[_Candidate, ...]:
        if self.max_options is None:
            return candidates
        if len(candidates) <= self.max_options:
            return candidates

        repeat = next(
            (
                candidate
                for candidate in candidates
                if candidate.cycle_action == "REPEAT"
            ),
            None,
        )
        repeat_gate = repeat.cycle_gate if repeat is not None else None
        exit_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate.cycle_action == "EXIT"
                and candidate.cycle_gate == repeat_gate
            ),
            None,
        )
        if exit_candidate is None:
            exit_candidate = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.cycle_action == "EXIT_PREPARATION"
                    and candidate.cycle_gate == repeat_gate
                ),
                None,
            )
        if repeat is None or exit_candidate is None:
            return candidates[:self.max_options]

        # A repeat/exit gate is one atomic control decision. Preserve both
        # sides even when the ordinary breadth cap is one, otherwise a caller
        # that follows visible advice can never choose to leave the cycle.
        visible_count = max(self.max_options, 2)
        protected = {id(repeat), id(exit_candidate)}
        selected = [
            candidate
            for candidate in candidates
            if id(candidate) in protected
        ]
        for candidate in candidates:
            if len(selected) >= visible_count:
                break
            if id(candidate) not in protected:
                selected.append(candidate)
        selected_ids = {id(candidate) for candidate in selected}
        return tuple(
            candidate
            for candidate in candidates
            if id(candidate) in selected_ids
        )

    def _candidate_state(
        self,
        replay: _ReplayState,
        candidate: _Candidate,
    ) -> _AdviceState:
        if (
            candidate.decision_index is None
            or candidate.decision_index == len(replay.decisions) - 1
        ):
            return replay.active
        return self._restore(
            replay.decisions[candidate.decision_index],
            replay,
        )

    def _candidate_action(
        self,
        replay: _ReplayState,
        candidate: _Candidate,
    ) -> ToolAction:
        if (
            candidate.decision_index is not None
            and candidate.decision_index < len(replay.decisions) - 1
        ):
            return "ALTERNATIVE"
        if replay.decisions:
            decision = replay.decisions[-1]
            if self._can_retry(
                decision.failure_counts.get(candidate.tool_name, 0)
            ):
                return "RETRY"
        if replay.recovering:
            return "ALTERNATIVE"
        return "RUN"

    def _activate_candidate(
        self,
        replay: _ReplayState,
        candidate: _Candidate,
    ) -> None:
        decision_index = candidate.decision_index
        if decision_index is None or not replay.decisions:
            self._prepare_unadvised_tool(replay, candidate.tool_name)
            return
        if decision_index < len(replay.decisions) - 1:
            replay.decisions = replay.decisions[: decision_index + 1]
            decision = replay.decisions[-1]
            decision.selected_option = None
            replay.active = self._restore(decision, replay)
            replay.blocked = False
        decision = replay.decisions[-1]
        if candidate.tool_name not in decision.options:
            decision.options += (candidate.tool_name,)

    def _prepare_unadvised_tool(
        self,
        replay: _ReplayState,
        tool_name: str,
        *,
        force_child: bool = False,
    ) -> None:
        replay.blocked = False
        if not replay.decisions:
            replay.decisions.append(
                _DecisionFrame(
                    checkpoint=self._copy_state(replay.active),
                    options=(tool_name,),
                )
            )
            return
        decision = replay.decisions[-1]
        if (
            not force_child
            and decision.selected_option is None
            and tool_name in decision.options
        ):
            return

        # Keep the unchosen advised decision as a restorable parent. The
        # deviating call gets its own retry budget and checkpoint.
        decision.selected_option = tool_name
        replay.decisions.append(
            _DecisionFrame(
                checkpoint=self._copy_state(replay.active),
                options=(tool_name,),
            )
        )

    def _proposed_plans_for_event(
        self,
        replay: _ReplayState,
        snapshot: AdviceSnapshot | None,
        event: ToolSucceeded | ToolFailed,
        snapshot_consumed: bool,
    ) -> tuple[Plan, ...]:
        if snapshot is not None and not snapshot_consumed:
            event_inputs = self._event_input_artifacts(event)
            matching_options = tuple(
                option
                for option in snapshot.options
                if self._advised_option_matches_inputs(
                    option,
                    event.tool_name,
                    event_inputs,
                )
            )
            route_keys = tuple(dict.fromkeys(
                route_key
                for option in matching_options
                for route_key in option.supporting_route_keys
            ))
            if route_keys:
                plans = self._plans_for_route_keys(route_keys)
                if plans:
                    return plans

            signatures = tuple(dict.fromkeys(
                signature
                for option in matching_options
                for signature in option.supporting_plan_signatures
            ))
            if signatures:
                plans = self._plans_for_signatures(signatures)
                if plans:
                    return plans

            route_keys = tuple(dict.fromkeys(
                route_key
                for option in snapshot.options
                for route_key in option.supporting_route_keys
            ))
            if route_keys:
                plans = self._plans_for_route_keys(route_keys)
                if plans:
                    return plans

            signatures = tuple(dict.fromkeys(
                signature
                for option in snapshot.options
                for signature in option.supporting_plan_signatures
            ))
            return self._plans_for_signatures(signatures)
        return self._plans_for_route_keys(
            replay.proposed_route_keys
        )

    def _network_continuation_plans(
        self,
        replay: _ReplayState,
    ) -> tuple[Plan, ...]:
        if not replay.deviating or replay.last_observed_tool is None:
            return ()
        tool = self.project.tool(replay.last_observed_tool)
        anchors = tuple(
            artifact.name
            for artifact in tool.outputs
            if artifact.name in replay.active.available_artifacts
        )
        if not anchors:
            return ()
        plans = tuple(
            self.project.tool_network.discover_continuation_plans(
                available_artifacts=tuple(
                    artifact_name
                    for artifact_name
                    in self.project.tool_network.artifact_names
                    if artifact_name
                    in replay.active.available_artifacts
                ),
                anchor_artifacts=anchors,
                target_artifacts=self.project.target_artifacts,
            )
        )
        for plan in plans:
            self._register_plan(plan)
        return plans

    def _plan_roots(
        self,
        plan: Plan,
        state: _AdviceState,
    ) -> tuple[str, ...]:
        initial_requirements = plan.input_requirements().initial_artifacts
        roots: list[str] = []
        for tool in plan.tools:
            blocked_by_internal_producer = False
            for artifact in tool.inputs:
                if plan.has_explicit_producers:
                    producers = set(plan.producers_for_input(
                        tool.name,
                        artifact.name,
                    ))
                    if not producers:
                        continue
                    if state.active_producers.get(
                        artifact.name
                    ) in producers:
                        continue
                    if (
                        artifact.name in initial_requirements
                        and plan.is_feedback_input(
                            tool.name,
                            artifact.name,
                        )
                    ):
                        continue
                    blocked_by_internal_producer = True
                    break

                if artifact.name in state.available_artifacts:
                    continue
                if artifact.name in initial_requirements:
                    continue
                producers = {
                    producer.name
                    for producer in plan.tools
                    if any(
                        output.name == artifact.name
                        for output in producer.outputs
                    )
                }
                if producers:
                    blocked_by_internal_producer = True
                    break
            if not blocked_by_internal_producer:
                roots.append(tool.name)
        return tuple(roots)

    def _supporting_plans(self, tool_name: str) -> tuple[Plan, ...]:
        return tuple(
            plan
            for plan in self.plans
            if plan.contains_tool(tool_name)
        )

    def _frontier_plans(
        self,
        state: _AdviceState,
        plans: Iterable[Plan],
        tool_name: str,
    ) -> tuple[Plan, ...]:
        """Return Plans for which a tool is valid at this exact state."""
        return tuple(
            plan
            for plan in plans
            if tool_name in self._plan_frontier(state, (plan,))
        )

    def _cycle_roles(
        self,
        state: _AdviceState,
        tool_name: str,
        plans: Iterable[Plan],
    ) -> tuple[tuple[tuple[str, ...], CycleAction], ...]:
        """Return this move's role at each entered structural cycle.

        Completed cycle members, rather than only the globally last tool,
        identify an active optimization visit. Independent prerequisite work
        may legitimately occur between the cycle result and its gate.
        """
        completed = set(state.completed_tools)
        roles_by_gate: dict[tuple[str, ...], set[CycleAction]] = {}
        for plan in plans:
            tool_graph = plan.to_tool_dependency_graph()
            if tool_name not in tool_graph:
                continue
            for component in nx.strongly_connected_components(tool_graph):
                if not (
                    len(component) > 1
                    or any(
                        tool_graph.has_edge(name, name)
                        for name in component
                    )
                ):
                    continue
                if not completed.intersection(component):
                    continue
                gate = tuple(
                    name
                    for name in self.project.tool_network.tool_names
                    if name in component
                )
                role: CycleAction | None = None
                if tool_name in component:
                    role = "REPEAT"
                else:
                    exit_tools = {
                        successor
                        for member in component
                        for successor in tool_graph.successors(member)
                        if successor not in component
                    }
                    if tool_name in exit_tools:
                        role = "EXIT"
                    elif any(
                        nx.has_path(tool_graph, tool_name, exit_tool)
                        for exit_tool in exit_tools
                    ):
                        role = "EXIT_PREPARATION"
                if role is not None:
                    roles_by_gate.setdefault(gate, set()).add(role)

        return tuple(
            (gate, next(iter(roles)))
            for gate, roles in roles_by_gate.items()
            if len(roles) == 1
        )

    def _mark_cycle_gate_candidates(
        self,
        state: _AdviceState,
        candidates: Iterable[_Candidate],
    ) -> tuple[_Candidate, ...]:
        """Expose cycle roles only at a real repeat-versus-exit gate."""
        candidates = tuple(candidates)
        roles_by_candidate = tuple(
            dict(self._cycle_roles(
                state,
                candidate.tool_name,
                candidate.supporting_plans,
            ))
            if candidate.transition is CandidateTransition.CONTINUE_CURRENT
            else {}
            for candidate in candidates
        )
        actions_by_gate: dict[tuple[str, ...], set[CycleAction]] = {}
        for roles in roles_by_candidate:
            for gate, action in roles.items():
                actions_by_gate.setdefault(gate, set()).add(action)

        acceptance_exit = (
            self._targets_ready(state)
            and self._acceptance_required(state)
        )
        eligible_gates = {
            gate
            for gate, actions in actions_by_gate.items()
            if "REPEAT" in actions
            and (
                acceptance_exit
                or "EXIT" in actions
                or "EXIT_PREPARATION" in actions
            )
        }
        marked: list[_Candidate] = []
        for candidate, roles in zip(
            candidates,
            roles_by_candidate,
            strict=True,
        ):
            selected = next(
                (
                    (gate, action)
                    for preferred_action in (
                        "REPEAT",
                        "EXIT",
                        "EXIT_PREPARATION",
                    )
                    for gate, action in roles.items()
                    if gate in eligible_gates
                    and action == preferred_action
                ),
                None,
            )
            marked.append(replace(
                candidate,
                cycle_action=(selected[1] if selected is not None else None),
                cycle_gate=(selected[0] if selected is not None else None),
            ))
        return tuple(marked)

    @staticmethod
    def _plan_signature(plan: Plan) -> tuple[str, ...]:
        return tuple(plan.tool_names)

    @staticmethod
    def _plan_route_key(plan: Plan) -> PlanRouteKey:
        return plan.route_key

    def _register_plan(self, plan: Plan) -> None:
        route_key = self._plan_route_key(plan)
        self._plans_by_route_key.setdefault(route_key, plan)
        signature = self._plan_signature(plan)
        existing = self._plans_by_signature.get(signature, ())
        if not any(
            self._plan_route_key(candidate) == route_key
            for candidate in existing
        ):
            self._plans_by_signature[signature] = (*existing, plan)

    def _plans_for_route_keys(
        self,
        route_keys: Iterable[PlanRouteKey],
    ) -> tuple[Plan, ...]:
        return tuple(
            plan
            for route_key in route_keys
            if (
                plan := self._plans_by_route_key.get(route_key)
            ) is not None
        )

    def _plans_for_signatures(
        self,
        signatures: Iterable[tuple[str, ...]],
    ) -> tuple[Plan, ...]:
        return tuple(dict(
            (
                self._plan_route_key(plan),
                plan,
            )
            for signature in signatures
            for plan in self._plans_by_signature.get(tuple(signature), ())
        ).values())

    def _missing_inputs(
        self,
        tool_name: str,
        state: _AdviceState,
    ) -> tuple[str, ...]:
        return tuple(
            artifact.name
            for artifact in self.project.tool(tool_name).inputs
            if artifact.name not in state.available_artifacts
        )

    def _event_matches_candidate_inputs(
        self,
        replay: _ReplayState,
        candidate: _Candidate,
        event: ToolSucceeded | ToolFailed,
    ) -> bool:
        state = self._candidate_state(replay, candidate)
        expected = {
            name: artifact
            for name, artifact in state.active_artifacts.items()
            if name in {
                tool_input.name
                for tool_input in self.project.tool(candidate.tool_name).inputs
            }
        }
        actual = {
            artifact.artifact_name: artifact
            for artifact in event.inputs
        }
        return all(
            actual.get(name) == artifact
            for name, artifact in expected.items()
        )

    def _candidate_input_artifacts(
        self,
        replay: _ReplayState,
        candidate: _Candidate,
    ) -> tuple[tuple[str, int], ...]:
        """Return the exact active inputs that identify one command."""
        state = self._candidate_state(replay, candidate)
        return self._state_input_artifacts(candidate.tool_name, state)

    def _state_input_artifacts(
        self,
        tool_name: str,
        state: _AdviceState,
    ) -> tuple[tuple[str, int], ...]:
        return tuple(
            (
                artifact.name,
                state.active_artifacts[artifact.name].version,
            )
            for artifact in self.project.tool(tool_name).inputs
            if artifact.name in state.active_artifacts
        )

    @staticmethod
    def _event_input_artifacts(
        event: ToolSucceeded | ToolFailed,
    ) -> tuple[tuple[str, int], ...]:
        return tuple(
            (artifact.artifact_name, artifact.version)
            for artifact in event.inputs
        )

    @staticmethod
    def _advised_option_matches_inputs(
        option: AdvisedOption,
        tool_name: str,
        event_inputs: tuple[tuple[str, int], ...],
    ) -> bool:
        """Match exact known bindings while allowing newly supplied inputs."""
        if option.tool_name != tool_name:
            return False
        actual = dict(event_inputs)
        return all(
            actual.get(name) == version
            for name, version in option.input_artifacts
        )

    def _snapshot_contains_event(
        self,
        snapshot: AdviceSnapshot | None,
        event: ToolSucceeded | ToolFailed,
    ) -> bool:
        if snapshot is None:
            return False
        event_inputs = self._event_input_artifacts(event)
        return any(
            self._advised_option_matches_inputs(
                option,
                event.tool_name,
                event_inputs,
            )
            for option in snapshot.options
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
            if self._can_retry(decision.failure_counts.get(tool_name, 0))
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
        state.active_artifacts.update(replay.external_artifacts)
        state.active_producers.update(
            (artifact_name, None)
            for artifact_name in replay.external_artifacts
        )
        return state

    @staticmethod
    def _copy_state(state: _AdviceState) -> _AdviceState:
        return _AdviceState(
            available_artifacts=set(state.available_artifacts),
            active_artifacts=dict(state.active_artifacts),
            active_producers=dict(state.active_producers),
            produced_artifacts=set(state.produced_artifacts),
            target_candidates=dict(state.target_candidates),
            next_tools=state.next_tools,
            route_keys=state.route_keys,
            completed_tools=state.completed_tools,
            last_tool=state.last_tool,
            targets_accepted=state.targets_accepted,
        )

    def _tool_option(
        self,
        tool_name: str,
        state: _AdviceState,
        action: ToolAction,
        depth: int,
        *,
        candidate: _Candidate | None = None,
    ) -> ToolOption:
        tool = self.project.tool(tool_name)
        input_artifacts = tuple(
            artifact.name
            for artifact in tool.inputs
        )
        execution_state = state
        renewable_targets = self._renewable_targets(state)
        if renewable_targets:
            execution_state = self._copy_state(state)
            execution_state.produced_artifacts.difference_update(
                renewable_targets
            )
            for target_name in renewable_targets:
                execution_state.target_candidates.pop(target_name, None)
            execution_state.targets_accepted = False

        next_state = self._after_tool(
            execution_state,
            tool,
            use_tool_network=(
                not self.project.workflow.contains_tool(tool_name)
                or (
                    candidate is not None
                    and candidate.scope is CandidateScope.TOOL_NETWORK
                )
            ),
            supporting_plans=(
                candidate.supporting_plans
                if candidate is not None
                else ()
            ),
        )
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
            next_candidates = self._preview_candidates(
                next_state,
                candidate,
            )
            visible_candidates = self._limit_candidates(next_candidates)
            options_truncated = (
                len(visible_candidates) < len(next_candidates)
            )
            continuations = tuple(
                self._tool_option(
                    next_candidate.tool_name,
                    next_state,
                    "RUN",
                    depth - 1,
                    candidate=next_candidate,
                )
                for next_candidate in visible_candidates
            )

        return ToolOption(
            tool_name=tool.name,
            missing_artifacts=tuple(
                artifact_name
                for artifact_name in input_artifacts
                if artifact_name not in state.available_artifacts
            ),
            input_artifacts=self._state_input_artifacts(tool_name, state),
            action=action,
            continuations=continuations,
            outcome=outcome,
            has_more=has_more,
            options_truncated=options_truncated,
            scope=(
                candidate.scope.name
                if candidate is not None
                else (
                    "WORKFLOW_PLAN"
                    if self.project.workflow.contains_tool(tool_name)
                    else "TOOL_NETWORK"
                )
            ),
            transition=(
                candidate.transition.name
                if candidate is not None
                else "CONTINUE_CURRENT"
            ),
            supporting_plans=(
                tuple(dict.fromkeys(
                    self._plan_signature(plan)
                    for plan in candidate.supporting_plans
                ))
                if candidate is not None
                else tuple(dict.fromkeys(
                    self._plan_signature(plan)
                    for plan in self._supporting_plans(tool_name)
                ))
            ),
            cycle_action=(
                candidate.cycle_action
                if candidate is not None
                else None
            ),
            supporting_route_keys=(
                tuple(dict.fromkeys(
                    self._plan_route_key(plan)
                    for plan in candidate.supporting_plans
                ))
                if candidate is not None
                else tuple(dict.fromkeys(
                    self._plan_route_key(plan)
                    for plan in self._supporting_plans(tool_name)
                ))
            ),
        )

    def _preview_candidates(
        self,
        state: _AdviceState,
        parent: _Candidate | None,
    ) -> tuple[_Candidate, ...]:
        """Rank success-assuming preview branches like executable roots."""
        candidates: list[_Candidate] = []
        for stable_order, tool_name in enumerate(state.next_tools):
            inherited_plans = self._frontier_plans(
                state,
                (
                    parent.supporting_plans
                    if parent is not None
                    else self.plans
                ),
                tool_name,
            )
            plans = inherited_plans
            if (
                parent is not None
                and parent.scope is CandidateScope.PROPOSED_PLAN
                and inherited_plans
            ):
                scope = CandidateScope.PROPOSED_PLAN
            elif self.project.workflow.contains_tool(tool_name):
                scope = CandidateScope.WORKFLOW_PLAN
            else:
                scope = CandidateScope.TOOL_NETWORK
            candidates.append(
                _Candidate(
                    tool_name=tool_name,
                    scope=scope,
                    transition=CandidateTransition.CONTINUE_CURRENT,
                    supporting_plans=plans,
                    remaining_tools=min(
                        (
                            len(
                                set(plan.tool_names)
                                - set(state.completed_tools)
                            )
                            for plan in plans
                        ),
                        default=len(self.project.tool_network.tools),
                    ),
                    stable_order=(
                        self._tool_positions.get(
                            tool_name,
                            len(self._tool_positions),
                        )
                        + stable_order * (len(self._tool_positions) + 1)
                    ),
                )
            )
        marked_candidates = self._mark_cycle_gate_candidates(
            state,
            candidates,
        )
        return tuple(sorted(
            marked_candidates,
            key=lambda option: self._preview_candidate_rank(state, option),
        ))

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

    def _state_is_complete(self, state: _AdviceState) -> bool:
        return self._targets_ready(state) and (
            not self._acceptance_required(state)
            or state.targets_accepted
        )

    def _acceptance_required(self, state: _AdviceState) -> bool:
        """Return whether a continuation can produce a fresh candidate."""
        return bool(self._renewable_targets(state))

    def _renewable_targets(
        self,
        state: _AdviceState,
    ) -> tuple[str, ...]:
        """Return ready targets that a continuation can produce again."""
        if not self._targets_ready(state) or not state.next_tools:
            return ()

        renewable: list[str] = []
        for target_name in self.project.target_artifacts:
            continuation = self._copy_state(state)
            continuation.produced_artifacts.discard(target_name)
            continuation.target_candidates.pop(target_name, None)
            continuation.targets_accepted = False
            if self._bootstrap_routes(continuation):
                renewable.append(target_name)
        return tuple(renewable)
