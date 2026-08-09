from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING

import networkx as nx

from artifactflow.network.network import Network
from artifactflow.tool.compatibility.tools_compatibility import tool_readiness
from artifactflow.similarity.qap import QAPStudy

if TYPE_CHECKING:
    from artifactflow.plan.plan import Plan
    from artifactflow.tool_network.tool_network import ToolNetwork


def _has_positive_length_path(
    graph: nx.DiGraph,
    start: str,
    target: str,
) -> bool:
    """Return whether a directed path traverses at least one edge."""
    if start not in graph or target not in graph:
        return False
    if start != target:
        return nx.has_path(graph, start, target)
    return any(
        nx.has_path(graph, successor, target)
        for successor in graph.successors(start)
    )


@dataclass(frozen=True, slots=True)
class WorkflowInputRequirements:
    """
    Artifacts needed to initialize and repeatedly run a workflow.
    """

    external_artifacts: frozenset[str]
    bootstrap_artifacts: frozenset[str]
    blocked_tools: frozenset[str]
    unreplenished_bootstrap_artifacts: frozenset[str]

    @property
    def initial_artifacts(self) -> frozenset[str]:
        """
        Return every artifact that must exist before the first run.
        """
        return self.external_artifacts | self.bootstrap_artifacts

    @property
    def is_runnable(self) -> bool:
        """
        Whether one run completes and replenishes its bootstrap inputs.
        """
        return (
            not self.blocked_tools
            and not self.unreplenished_bootstrap_artifacts
        )

    def __str__(self):
        return f'''
            "External Artifacts": {list(self.external_artifacts)},
            "Bootstrap Artifacts": {list(self.bootstrap_artifacts)},
        '''


class Workflow(
    Network,
):

    def __init__(self):
        super().__init__()

        self.starting_artifacts: list[str] | None = None
        self.target_artifacts: list[str] | None = None

    def to_tool_network(self) -> ToolNetwork:
        """Return an independent tool network with the same definition."""
        from artifactflow.tool_network.tool_network import ToolNetwork

        tool_network = ToolNetwork()
        for tool in self.tools:
            tool_network.add_tool(tool)
        tool_network.starting_artifacts = deepcopy(self.starting_artifacts)
        tool_network.target_artifacts = deepcopy(self.target_artifacts)
        return tool_network

    def discover_plans(
        self,
        starting_artifacts: Iterable[str] | None = None,
        target_artifacts: Iterable[str] | None = None,
    ) -> list[Plan]:
        """Return every minimal target-reaching plan in this workflow.

        Alternative producers create separate plans. Tools in a directed
        cycle are treated as one indivisible unit, so a repeatable cycle does
        not create infinitely many plans for different iteration counts. The
        search is exhaustive and therefore best suited to bounded workflows.
        """
        from artifactflow.plan.plan import Plan

        starts = self._plan_boundary(
            "starting_artifacts",
            starting_artifacts,
            self.starting_artifacts,
        )
        targets = self._plan_boundary(
            "target_artifacts",
            target_artifacts,
            self.target_artifacts,
        )
        if not targets:
            raise ValueError("target_artifacts cannot be empty.")

        unknown_artifacts = (
            set(starts) | set(targets)
        ) - set(self.artifact_names)
        if unknown_artifacts:
            raise ValueError(
                f"Unknown artifacts: {sorted(unknown_artifacts)}"
            )

        tool_graph = self.to_tool_dependency_graph()
        tool_positions = {
            tool.name: position
            for position, tool in enumerate(self.tools)
        }
        tool_units = [
            frozenset(component)
            for component in nx.strongly_connected_components(tool_graph)
        ]
        tool_units.sort(
            key=lambda unit: min(tool_positions[name] for name in unit)
        )

        valid_tool_sets: list[frozenset[str]] = []
        for unit_count in range(1, len(tool_units) + 1):
            for selected_units in combinations(tool_units, unit_count):
                selected_tools = frozenset().union(*selected_units)
                if self._is_valid_plan(
                    selected_tools,
                    starts,
                    targets,
                ):
                    valid_tool_sets.append(selected_tools)

        minimal_tool_sets = [
            selected_tools
            for selected_tools in valid_tool_sets
            if not any(
                other_tools < selected_tools
                for other_tools in valid_tool_sets
            )
        ]
        minimal_tool_sets.sort(
            key=lambda names: tuple(
                position
                for position, tool in enumerate(self.tools)
                if tool.name in names
            )
        )

        plans: list[Plan] = []
        for selected_tools in minimal_tool_sets:
            plan = Plan()
            for tool in self.tools:
                if tool.name in selected_tools:
                    plan.add_tool(tool)
            plan.starting_artifacts = list(starts)
            plan.target_artifacts = list(targets)
            plans.append(plan)
        return plans

    def _is_valid_plan(
        self,
        selected_tools: frozenset[str],
        starting_artifacts: tuple[str, ...],
        target_artifacts: tuple[str, ...],
    ) -> bool:
        """Return whether a tool subset is one complete plan."""
        selected = [
            tool
            for tool in self.tools
            if tool.name in selected_tools
        ]
        produced_artifacts = {
            artifact.name
            for tool in selected
            for artifact in tool.outputs
        }
        if not set(target_artifacts) <= produced_artifacts:
            return False

        starting_names = set(starting_artifacts)
        for tool in selected:
            for artifact in tool.inputs:
                if artifact.name in starting_names:
                    continue
                producers = {
                    producer_name
                    for producer_name in self.G.predecessors(artifact.name)
                    if self.G.nodes[producer_name].get("type") == "tool"
                }
                if producers and not producers & selected_tools:
                    return False

        relevant_nodes = set(selected_tools)
        relevant_nodes.update(
            artifact.name
            for tool in selected
            for artifact in (*tool.inputs, *tool.outputs)
        )
        plan_graph = self.G.subgraph(relevant_nodes)

        if any(
            not _has_positive_length_path(plan_graph, start, target)
            for start in starting_artifacts
            for target in target_artifacts
        ):
            return False

        return all(
            any(
                nx.has_path(plan_graph, tool.name, target)
                for target in target_artifacts
            )
            for tool in selected
        )

    @staticmethod
    def _plan_boundary(
        name: str,
        provided: Iterable[str] | None,
        stored: list[str] | None,
    ) -> tuple[str, ...]:
        value = provided if provided is not None else stored
        if value is None:
            raise ValueError(
                f"{name} must be provided because the workflow does not "
                "define it."
            )
        return tuple(dict.fromkeys(value))

    def following_tools(
        self,
        tool_names: str | Iterable[str],
    ) -> tuple[str, ...]:
        """Return tools that consume an output of the given tool or tools."""
        names = (
            (tool_names,)
            if isinstance(tool_names, str)
            else tuple(tool_names)
        )
        unknown = set(names) - set(self.tool_names)
        if unknown:
            raise ValueError(f"Unknown tools: {sorted(unknown)}")

        output_artifacts = {
            artifact.name
            for tool in self.tools
            if tool.name in names
            for artifact in tool.outputs
        }
        return tuple(
            tool.name
            for tool in self.tools
            if any(
                artifact.name in output_artifacts
                for artifact in tool.inputs
            )
        )

    def input_requirements(
        self,
        starting_tools: list[str],
    ) -> WorkflowInputRequirements:
        """
        Analyze persistent external inputs and first-run bootstrap inputs.

        Starting tools are required to execute before any other tools. Their
        internally produced inputs must therefore be supplied for the first
        run. The method then simulates one run to check that all tools can
        execute and that those bootstrap artifacts are produced again.
        """
        if not starting_tools:
            raise ValueError("At least one starting tool is required.")

        starting_tool_names = set(starting_tools)
        available_tool_names = set(self.tool_names)
        unknown_tools = starting_tool_names - available_tool_names

        if unknown_tools:
            raise ValueError(
                f"Unknown starting tools: {sorted(unknown_tools)}"
            )

        external_artifacts = {
            artifact_name
            for artifact_name, data in self.G.nodes(data=True)
            if data["type"] == "artifact"
            and any(
                self.G.nodes[consumer_name]["type"] == "tool"
                for consumer_name in self.G.successors(artifact_name)
            )
            and not any(
                self.G.nodes[producer_name]["type"] == "tool"
                for producer_name in self.G.predecessors(artifact_name)
            )
        }

        bootstrap_artifacts = {
            artifact.name
            for tool in self.tools
            if tool.name in starting_tool_names
            for artifact in tool.inputs
            if any(
                self.G.nodes[producer_name]["type"] == "tool"
                for producer_name in self.G.predecessors(artifact.name)
            )
        }

        available_artifacts = (
            external_artifacts | bootstrap_artifacts
        )
        executed_tool_names = set(starting_tool_names)
        produced_artifacts = {
            artifact.name
            for tool in self.tools
            if tool.name in starting_tool_names
            for artifact in tool.outputs
        }
        available_artifacts.update(produced_artifacts)

        made_progress = True

        while made_progress:
            made_progress = False

            for tool in self.tools:
                if tool.name in executed_tool_names:
                    continue

                input_names = {
                    artifact.name
                    for artifact in tool.inputs
                }

                if not input_names <= available_artifacts:
                    continue

                output_names = {
                    artifact.name
                    for artifact in tool.outputs
                }
                executed_tool_names.add(tool.name)
                produced_artifacts.update(output_names)
                available_artifacts.update(output_names)
                made_progress = True

        blocked_tools = (
            available_tool_names - executed_tool_names
        )
        unreplenished_bootstrap_artifacts = (
            bootstrap_artifacts - produced_artifacts
        )

        return WorkflowInputRequirements(
            external_artifacts=frozenset(external_artifacts),
            bootstrap_artifacts=frozenset(bootstrap_artifacts),
            blocked_tools=frozenset(blocked_tools),
            unreplenished_bootstrap_artifacts=frozenset(
                unreplenished_bootstrap_artifacts
            ),
        )

    def tool_readiness_scores(
        self,
        missing_input_penalty_ratio: float = 1.0,
    ) -> dict[str, float]:
        """
        Return readiness scores for tools with internal producers.
        """
        if missing_input_penalty_ratio < 0:
            raise ValueError(
                "missing_input_penalty_ratio cannot be negative."
            )

        scores = {}

        for candidate_tool in self.tools:
            producer_names = {
                producer_name
                for artifact_name in self.G.predecessors(candidate_tool.name)
                for producer_name in self.G.predecessors(artifact_name)
                if producer_name != candidate_tool.name
                and self.G.nodes[producer_name]["type"] == "tool"
            }

            if not producer_names:
                continue

            previous_tools = [
                tool
                for tool in self.tools
                if tool.name in producer_names
            ]

            scores[candidate_tool.name] = tool_readiness(
                previous_tools=previous_tools,
                candidate_tool=candidate_tool,
                missing_input_penalty_ratio=missing_input_penalty_ratio,
            )

        return scores

    def compatibility_score(
        self,
        missing_input_penalty_ratio: float = 1.0,
    ) -> float:
        """
        Return the mean readiness of tools with internal producers.

        A workflow without tool-to-tool handoffs has no incompatibilities and
        therefore receives a score of 1.0.
        """
        scores = self.tool_readiness_scores(
            missing_input_penalty_ratio=missing_input_penalty_ratio,
        )

        if not scores:
            return 1.0

        return sum(scores.values()) / len(scores)

    def similarity_score(self, other: Workflow) -> float:
        """
        Return the observed typed-node QAP correlation with another workflow.

        The workflows are aligned to the union of their tool and artifact
        nodes. This method does not run a permutation significance test.
        """
        if not isinstance(other, Workflow):
            raise TypeError("other must be a Workflow.")

        study = QAPStudy(
            networks={
                "Workflow A": self.G,
                "Workflow B": other.G,
            },
        )
        return study.correlation("Workflow A", "Workflow B")

    def __add__(
        self,
        other: Workflow,
    ) -> ToolNetwork:
        from artifactflow.tool_network.tool_network import ToolNetwork

        if not isinstance(other, Workflow):
            raise TypeError(
                "other must be a Workflow."
            )
        result = ToolNetwork()

        if self.starting_artifacts is not None and \
        other.starting_artifacts is not None:
            if self.starting_artifacts == other.starting_artifacts:
                result.starting_artifacts = deepcopy(self.starting_artifacts)
        if self.target_artifacts is not None and \
        other.target_artifacts is not None:
            if self.target_artifacts == other.target_artifacts:
                result.target_artifacts = deepcopy(self.target_artifacts)
        
        for tool in self.tools:
            result.add_tool(tool)
        for tool in other.tools:
            if tool.name not in result.tool_names:
                result.add_tool(tool)

        return result


if __name__ == "__main__":

    from artifactflow.tool.examples import tool_1, tool_2, tool_3, tool_4

    workflow = Workflow()
    workflow.add_tool(tool_1)
    workflow.add_tool(tool_2)
    workflow.add_tool(tool_3)
    workflow.add_tool(tool_4)

    print(workflow.compatibility_score())
    print(workflow.input_requirements(starting_tools=["Tool 2"]))

    workflow.show()
