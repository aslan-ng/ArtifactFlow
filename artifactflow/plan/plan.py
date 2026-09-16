"""
One target-reaching plan selected from a workflow.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, TypeAlias

import networkx as nx

from artifactflow.network.network import Network

if TYPE_CHECKING:
    from artifactflow.workflow.workflow import Workflow


InputProducerBinding: TypeAlias = tuple[str, str, tuple[str, ...]]
TargetProducerBinding: TypeAlias = tuple[str, tuple[str, ...]]
PlanRouteKey: TypeAlias = tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[InputProducerBinding, ...],
    tuple[TargetProducerBinding, ...],
]


@dataclass(frozen=True, slots=True)
class PlanRequirements:
    """
    External inputs and one chosen bootstrap set for one plan.
    """

    external_artifacts: frozenset[str]
    bootstrap_artifacts: frozenset[str]

    @property
    def initial_artifacts(self) -> frozenset[str]:
        """
        Return everything that must be available to start the plan.
        """
        return self.external_artifacts | self.bootstrap_artifacts

    @property
    def is_satisfied(self) -> bool:
        """
        Return whether this requirement set is empty.
        """
        return not self.initial_artifacts

    def missing(
        self,
        available_artifacts: Iterable[str],
    ) -> PlanRequirements:
        """
        Return requirements not present in an available artifact set.
        """
        available = _artifact_names(available_artifacts)
        return PlanRequirements(
            external_artifacts=self.external_artifacts - available,
            bootstrap_artifacts=self.bootstrap_artifacts - available,
        )


class Plan(Network):
    """
    A target-reaching subset of a workflow.

    A discovered plan contains the tools and selected producer bindings for
    one possible route through a workflow. Two plans may contain the same
    tools but bind an input to different producers. Tools that form a cycle
    are kept together, so a plan is a subnetwork rather than a finite sequence
    of tool calls.
    """

    def __init__(self) -> None:
        super().__init__()
        self.starting_artifacts: list[str] | None = None
        self.target_artifacts: list[str] | None = None
        self._input_producers: (
            dict[tuple[str, str], tuple[str, ...]] | None
        ) = None
        self._target_producers: (
            dict[str, tuple[str, ...]] | None
        ) = None

    @property
    def has_explicit_producers(self) -> bool:
        """
        Return whether this Plan carries route-specific producer edges.
        """
        return self._input_producers is not None

    @property
    def input_producers(
        self,
    ) -> tuple[InputProducerBinding, ...]:
        """
        Return route-specific producers for every concrete tool input.

        An empty producer tuple means that the input is external to this
        Plan. The property is empty for legacy or manually assembled Plans
        whose dependencies still follow every matching artifact edge.
        """
        if self._input_producers is None:
            return ()
        return tuple(
            (tool_name, artifact_name, producers)
            for (tool_name, artifact_name), producers
            in self._input_producers.items()
        )

    @property
    def target_producers(self) -> tuple[TargetProducerBinding, ...]:
        """
        Return the producers selected for each target artifact.
        """
        if self._target_producers is None:
            return ()
        return tuple(self._target_producers.items())

    @property
    def route_key(self) -> PlanRouteKey:
        """
        Return a stable identity including route-specific provenance.

        Tool names alone are not sufficient: two routes may contain exactly
        the same tools while binding a shared input to different producers.
        """
        return (
            tuple(self.tool_names),
            tuple(self.starting_artifacts or ()),
            tuple(self.target_artifacts or ()),
            self.input_producers,
            self.target_producers,
        )

    def set_input_producers(
        self,
        producers: Mapping[
            tuple[str, str],
            Iterable[str],
        ],
    ) -> None:
        """
        Bind each tool input to the producers selected for this route.

        Discovered Plans use these bindings to distinguish, for example, a
        direct producer from a longer refinement producer even when both
        create the same artifact type. Manually assembled Plans retain the
        original all-matching-producers behavior until this method is called.
        """
        if not isinstance(producers, Mapping):
            raise TypeError("producers must be a mapping.")

        expected = {
            (tool.name, artifact.name)
            for tool in self.tools
            for artifact in tool.inputs
        }
        if set(producers) != expected:
            missing = expected - set(producers)
            unknown = set(producers) - expected
            details: list[str] = []
            if missing:
                details.append(f"missing bindings: {sorted(missing)}")
            if unknown:
                details.append(f"unknown bindings: {sorted(unknown)}")
            raise ValueError(
                "Producer bindings must cover every Plan input ("
                + "; ".join(details)
                + ")."
            )

        tool_positions = {
            tool.name: position
            for position, tool in enumerate(self.tools)
        }
        tools_by_name = {
            tool.name: tool
            for tool in self.tools
        }
        normalized: dict[tuple[str, str], tuple[str, ...]] = {}
        ordered_inputs = (
            (tool.name, artifact.name)
            for tool in self.tools
            for artifact in tool.inputs
        )
        for key in ordered_inputs:
            producer_names = producers[key]
            consumer_name, artifact_name = key
            try:
                names = tuple(dict.fromkeys(producer_names))
            except TypeError:
                raise TypeError(
                    "Each producer binding must contain tool names."
                ) from None
            if not all(isinstance(name, str) for name in names):
                raise TypeError(
                    "Each producer binding must contain tool names."
                )
            unknown_names = set(names) - set(tools_by_name)
            if unknown_names:
                raise ValueError(
                    f"Unknown producer tools: {sorted(unknown_names)}"
                )
            invalid_names = {
                name
                for name in names
                if not any(
                    artifact.name == artifact_name
                    for artifact in tools_by_name[name].outputs
                )
            }
            if invalid_names:
                raise ValueError(
                    f"Tools {sorted(invalid_names)} do not produce "
                    f"artifact {artifact_name!r}."
                )
            normalized[(consumer_name, artifact_name)] = tuple(sorted(
                names,
                key=tool_positions.__getitem__,
            ))

        self._input_producers = normalized

    def set_target_producers(
        self,
        producers: Mapping[str, Iterable[str]],
    ) -> None:
        """
        Bind every target artifact to this route's selected producers.
        """
        if not isinstance(producers, Mapping):
            raise TypeError("producers must be a mapping.")
        if self.target_artifacts is None:
            raise ValueError(
                "target_artifacts must be defined before binding their "
                "producers."
            )

        expected = set(self.target_artifacts)
        if set(producers) != expected:
            missing = expected - set(producers)
            unknown = set(producers) - expected
            details: list[str] = []
            if missing:
                details.append(f"missing bindings: {sorted(missing)}")
            if unknown:
                details.append(f"unknown bindings: {sorted(unknown)}")
            raise ValueError(
                "Producer bindings must cover every Plan target ("
                + "; ".join(details)
                + ")."
            )

        tool_positions = {
            tool.name: position
            for position, tool in enumerate(self.tools)
        }
        tools_by_name = {
            tool.name: tool
            for tool in self.tools
        }
        normalized: dict[str, tuple[str, ...]] = {}
        for artifact_name in self.target_artifacts:
            producer_names = producers[artifact_name]
            try:
                names = tuple(dict.fromkeys(producer_names))
            except TypeError:
                raise TypeError(
                    "Each target binding must contain tool names."
                ) from None
            if not names:
                raise ValueError(
                    f"Target {artifact_name!r} needs at least one producer."
                )
            if not all(isinstance(name, str) for name in names):
                raise TypeError(
                    "Each target binding must contain tool names."
                )
            unknown_names = set(names) - set(tools_by_name)
            if unknown_names:
                raise ValueError(
                    f"Unknown producer tools: {sorted(unknown_names)}"
                )
            invalid_names = {
                name
                for name in names
                if not any(
                    artifact.name == artifact_name
                    for artifact in tools_by_name[name].outputs
                )
            }
            if invalid_names:
                raise ValueError(
                    f"Tools {sorted(invalid_names)} do not produce "
                    f"artifact {artifact_name!r}."
                )
            normalized[artifact_name] = tuple(sorted(
                names,
                key=tool_positions.__getitem__,
            ))

        self._target_producers = normalized

    def producers_for_input(
        self,
        tool_name: str,
        artifact_name: str,
    ) -> tuple[str, ...]:
        """
        Return producer tools selected for one input in this Plan.
        """
        key = (tool_name, artifact_name)
        if self._input_producers is not None:
            if key not in self._input_producers:
                raise ValueError(
                    f"Unknown Plan input binding: {key!r}"
                )
            return self._input_producers[key]
        return tuple(
            tool.name
            for tool in self.tools
            if any(
                artifact.name == artifact_name
                for artifact in tool.outputs
            )
        )

    def to_tool_dependency_graph(self) -> nx.DiGraph:
        """
        Return the producer-resolved tool graph for this Plan.
        """
        if self._input_producers is None:
            return super().to_tool_dependency_graph()

        graph = nx.DiGraph()
        graph.add_nodes_from(
            (tool.name, {"type": "tool"})
            for tool in self.tools
        )
        for tool in self.tools:
            for artifact in tool.inputs:
                for producer_name in self.producers_for_input(
                    tool.name,
                    artifact.name,
                ):
                    if graph.has_edge(producer_name, tool.name):
                        graph[producer_name][tool.name]["artifacts"].append(
                            artifact.name
                        )
                    else:
                        graph.add_edge(
                            producer_name,
                            tool.name,
                            artifacts=[artifact.name],
                        )
        return graph

    def is_feedback_input(
        self,
        tool_name: str,
        artifact_name: str,
    ) -> bool:
        """
        Return whether an input is an edge inside a selected cycle.
        """
        producers = self.producers_for_input(tool_name, artifact_name)
        if not producers:
            return False
        tool_graph = self.to_tool_dependency_graph()
        return any(
            tool_name in component
            and any(producer in component for producer in producers)
            and (
                len(component) > 1
                or tool_graph.has_edge(tool_name, tool_name)
            )
            for component in nx.strongly_connected_components(tool_graph)
        )

    def input_requirements(self) -> PlanRequirements:
        """
        Return the plan's structural external and bootstrap inputs.

        External artifacts have no producer in this plan. Bootstrap artifacts
        do have a producer, but an initial version is needed to enter a cycle.
        Declared internal starting artifacts are honored. If the plan needs
        further seeds, the smallest added set is selected; artifact insertion
        order resolves equally small alternatives deterministically.
        """
        if self.starting_artifacts is None:
            raise ValueError(
                "starting_artifacts must be defined before calculating "
                "plan requirements."
            )

        starting = set(self.starting_artifacts)
        unknown = starting - set(self.artifact_names)
        if unknown:
            raise ValueError(f"Unknown artifacts: {sorted(unknown)}")

        if self._input_producers is not None:
            return self._resolved_input_requirements(starting)

        consumed = {
            artifact.name
            for tool in self.tools
            for artifact in tool.inputs
        }
        produced = {
            artifact.name
            for tool in self.tools
            for artifact in tool.outputs
        }
        external = consumed - produced
        bootstrap = starting & consumed & produced

        initial = starting | external
        if not self._can_run_once(initial):
            candidates = [
                artifact_name
                for artifact_name in self.artifact_names
                if artifact_name in consumed & produced
                and artifact_name not in initial
            ]
            for number_of_seeds in range(1, len(candidates) + 1):
                selected = next(
                    (
                        set(seeds)
                        for seeds in combinations(
                            candidates,
                            number_of_seeds,
                        )
                        if self._can_run_once(initial | set(seeds))
                    ),
                    None,
                )
                if selected is not None:
                    bootstrap.update(selected)
                    break
            else:
                raise ValueError(
                    "The plan cannot be initialized from its declared "
                    "starting and external artifacts."
                )

        return PlanRequirements(
            external_artifacts=frozenset(external),
            bootstrap_artifacts=frozenset(bootstrap),
        )

    def _resolved_input_requirements(
        self,
        starting: set[str],
    ) -> PlanRequirements:
        """
        Return requirements using this route's producer selections.
        """
        external = {
            artifact.name
            for tool in self.tools
            for artifact in tool.inputs
            if not self.producers_for_input(tool.name, artifact.name)
        }
        tool_graph = self.to_tool_dependency_graph()
        cyclic_components = [
            component
            for component in nx.strongly_connected_components(tool_graph)
            if len(component) > 1
            or any(tool_graph.has_edge(name, name) for name in component)
        ]
        candidates = list(dict.fromkeys(
            artifact.name
            for tool in self.tools
            for artifact in tool.inputs
            if any(
                producer in component and tool.name in component
                for component in cyclic_components
                for producer in self.producers_for_input(
                    tool.name,
                    artifact.name,
                )
            )
        ))
        # A declared boundary that enters a selected feedback edge is an
        # intentional bootstrap choice, not merely one of several equivalent
        # seeds. Honor it before finding any additional minimal seeds.
        bootstrap: set[str] = starting & set(candidates)
        initial = set(external) | bootstrap

        if not self._can_run_once(initial):
            candidates = [
                artifact_name
                for artifact_name in candidates
                if artifact_name not in bootstrap
            ]
            candidates.sort(
                key=lambda artifact_name: (
                    artifact_name not in starting,
                    self.artifact_names.index(artifact_name),
                )
            )
            for number_of_seeds in range(1, len(candidates) + 1):
                selected = next(
                    (
                        set(seeds)
                        for seeds in combinations(
                            candidates,
                            number_of_seeds,
                        )
                        if self._can_run_once(initial | set(seeds))
                    ),
                    None,
                )
                if selected is not None:
                    bootstrap.update(selected)
                    break
            else:
                raise ValueError(
                    "The producer-resolved Plan cannot be initialized from "
                    "its external artifacts and cycle seeds."
                )

        return PlanRequirements(
            external_artifacts=frozenset(external),
            bootstrap_artifacts=frozenset(bootstrap),
        )

    def missing_input_requirements(
        self,
        available_artifacts: Iterable[str],
    ) -> PlanRequirements:
        """
        Return the plan requirements not currently available.
        """
        return self.input_requirements().missing(available_artifacts)

    def _can_run_once(self, initial_artifacts: set[str]) -> bool:
        """
        Return whether every plan tool can run once from these artifacts.
        """
        available = set(initial_artifacts)
        executed: set[str] = set()
        remaining = list(self.tools)

        while remaining:
            if self._input_producers is None:
                ready_tools = [
                    tool
                    for tool in remaining
                    if {
                        artifact.name
                        for artifact in tool.inputs
                    } <= available
                ]
            else:
                ready_tools = []
                for tool in remaining:
                    ready = True
                    for artifact in tool.inputs:
                        producers = self.producers_for_input(
                            tool.name,
                            artifact.name,
                        )
                        if producers:
                            if not (
                                set(producers) & executed
                                or (
                                    artifact.name in initial_artifacts
                                    and self.is_feedback_input(
                                        tool.name,
                                        artifact.name,
                                    )
                                )
                            ):
                                ready = False
                                break
                        elif artifact.name not in available:
                            ready = False
                            break
                    if ready:
                        ready_tools.append(tool)
            if not ready_tools:
                return False

            for tool in ready_tools:
                available.update(
                    artifact.name
                    for artifact in tool.outputs
                )
                executed.add(tool.name)
                remaining.remove(tool)

        return True

    @classmethod
    def from_workflow(cls, workflow: Workflow) -> Plan:
        """
        Create a plan containing the same tools and boundaries.
        """
        from artifactflow.workflow.workflow import Workflow

        if not isinstance(workflow, Workflow):
            raise TypeError("workflow must be a Workflow.")

        plan = cls()
        for tool in workflow.tools:
            plan.add_tool(tool)
        plan.starting_artifacts = deepcopy(workflow.starting_artifacts)
        plan.target_artifacts = deepcopy(workflow.target_artifacts)
        return plan


def _artifact_names(artifacts: Iterable[str]) -> frozenset[str]:
    names = (artifacts,) if isinstance(artifacts, str) else tuple(artifacts)
    if not all(isinstance(name, str) for name in names):
        raise TypeError("available_artifacts must contain artifact names.")
    return frozenset(names)
