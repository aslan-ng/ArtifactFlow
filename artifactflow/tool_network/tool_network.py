from __future__ import annotations

from collections.abc import Hashable, Iterable
from itertools import combinations
import networkx as nx
from copy import deepcopy

from artifactflow.plan.plan import Plan
from artifactflow.similarity.qap import QAPStudy
from artifactflow.network.network import Network
from artifactflow.workflow.workflow import Workflow


def _has_positive_length_path(
    graph: nx.DiGraph,
    start: Hashable,
    target: Hashable,
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


class ToolNetwork(
    Network,
):

    def __init__(self):
        super().__init__()

        self.starting_artifacts: list[str] | None = None
        self.target_artifacts: list[str] | None = None
        self.include_tools: list[str] | None = None
        self.exclude_tools: list[str] | None = None

    def contains_workflow(self, workflow: Workflow) -> bool:
        """Return whether this network contains the complete workflow.

        Matching tool names must declare the same input and output artifacts.
        Tool order and the workflow's starting and target boundaries do not
        affect structural containment.
        """
        if not isinstance(workflow, Workflow):
            raise TypeError("workflow must be a Workflow.")

        tools_by_name = {
            tool.name: tool
            for tool in self.tools
        }
        for workflow_tool in workflow.tools:
            network_tool = tools_by_name.get(workflow_tool.name)
            if network_tool is None:
                return False

            workflow_inputs = {
                artifact.name
                for artifact in workflow_tool.inputs
            }
            network_inputs = {
                artifact.name
                for artifact in network_tool.inputs
            }
            workflow_outputs = {
                artifact.name
                for artifact in workflow_tool.outputs
            }
            network_outputs = {
                artifact.name
                for artifact in network_tool.outputs
            }
            if (
                workflow_inputs != network_inputs
                or workflow_outputs != network_outputs
            ):
                return False

        return True

    def __add__(
        self,
        other: ToolNetwork | Workflow,
    ) -> ToolNetwork:
        """
        Return a new tool network containing the union of both operands.

        The right operand may be a Workflow or ToolNetwork. Tool order is
        preserved from the left operand, followed by new tools from the right
        operand. Filter memory is intentionally reset on the returned network.
        """
        if not isinstance(other, (Workflow, ToolNetwork)):
            raise ValueError("incompatible format")

        result = ToolNetwork()
        for tool in self.tools:
            result.add_tool(tool)
        for tool in other.tools:
            if tool.name not in result.tool_names:
                result.add_tool(tool)
        
        return result

    def __sub__(
        self,
        other: ToolNetwork | Workflow,
    ) -> ToolNetwork:
        """
        Return a new tool network.

        The right operand may be a Workflow or ToolNetwork. Tool order is
        preserved from the left operand, followed by new tools from the right
        operand. Filter memory is NOT reset on the returned network.
        """
        if not isinstance(other, (Workflow, ToolNetwork)):
            raise ValueError("incompatible format")

        result = deepcopy(self)
        for tool in other.tools:
            if tool.name in result.tool_names:
                result.remove_tool(tool.name)
        
        return result

    def to_workflow(self) -> Workflow:
        """
        Convert this tool network into one workflow.

        The network must be connected to represent one process.
        """
        if not self.tools:
            raise ValueError(
                "Cannot create a workflow from an empty tool network."
            )

        workflow = Workflow()

        for tool in self.tools:
            workflow.add_tool(tool)

        if not nx.is_weakly_connected(workflow.G):
            raise ValueError(
                "The tool network contains disconnected processes, "
                "so it cannot become one workflow."
            )

        return workflow

    def filter(
        self,
        starting_artifacts: list[str] | None = None,
        target_artifacts: list[str] | None = None,
        include_tools: list[str] | None = None,
        exclude_tools: list[str] | None = None,
    ) -> "ToolNetwork":
        """
        Filter tools in the tool network
        """

        tools_by_name = {
            str(tool.name): tool
            for tool in self.tools
        }

        available_tool_names = set(tools_by_name)

        included_names = (
            set(include_tools)
            if include_tools is not None
            else available_tool_names
        )

        excluded_names = set(exclude_tools or [])

        unknown_tools = (
            included_names | excluded_names
        ) - available_tool_names

        if unknown_tools:
            raise ValueError(
                f"Unknown tools: {sorted(unknown_tools)}"
            )

        selected_names = (
            included_names - excluded_names
        )

        candidate = ToolNetwork()

        for tool in self.tools:
            if tool.name in selected_names:
                candidate.add_tool(tool)

        artifact_names = {
            node
            for node, data in candidate.G.nodes(data=True)
            if data["type"] == "artifact"
        }

        requested_artifacts = (
            set(starting_artifacts or [])
            | set(target_artifacts or [])
        )

        unknown_artifacts = (
            requested_artifacts - artifact_names
        )

        if unknown_artifacts:
            raise ValueError(
                f"Unknown artifacts: {sorted(unknown_artifacts)}"
            )

        relevant_nodes = set(candidate.G.nodes)

        if starting_artifacts is not None:
            forward_nodes = set(starting_artifacts)

            for artifact in starting_artifacts:
                forward_nodes.update(
                    nx.descendants(candidate.G, artifact)
                )

            relevant_nodes &= forward_nodes

        if target_artifacts is not None:
            backward_nodes = set(target_artifacts)

            for artifact in target_artifacts:
                backward_nodes.update(
                    nx.ancestors(candidate.G, artifact)
                )

            relevant_nodes &= backward_nodes

        filtered = ToolNetwork()

        for tool in candidate.tools:
            if tool.name in relevant_nodes:
                filtered.add_tool(tool)

        filtered.starting_artifacts = (
            None
            if starting_artifacts is None
            else list(starting_artifacts)
        )
        filtered.target_artifacts = (
            None
            if target_artifacts is None
            else list(target_artifacts)
        )
        filtered.include_tools = (
            None
            if include_tools is None
            else list(include_tools)
        )
        filtered.exclude_tools = (
            None
            if exclude_tools is None
            else list(exclude_tools)
        )

        return filtered

    def discover(self) -> list[Workflow]:
        """
        Create every workflow that satisfies this tool network's filters.

        Workflows are returned largest first. Tools within each workflow keep
        their insertion order from the tool network.
        """
        workflows = []

        for tool_count in range(len(self.tools), 0, -1):
            for tools in combinations(self.tools, tool_count):
                workflow = Workflow()

                for tool in tools:
                    workflow.add_tool(tool)

                if not nx.is_weakly_connected(workflow.G):
                    continue

                workflow_tool_names = set(workflow.tool_names)

                if (
                    self.include_tools is not None
                    and not set(self.include_tools) <= workflow_tool_names
                ):
                    continue

                if (
                    self.exclude_tools is not None
                    and set(self.exclude_tools) & workflow_tool_names
                ):
                    continue

                starting_artifacts = self.starting_artifacts or []
                target_artifacts = self.target_artifacts or []

                if not set(starting_artifacts) <= workflow.G.nodes:
                    continue

                if not set(target_artifacts) <= workflow.G.nodes:
                    continue

                targets_are_produced = all(
                    any(
                        workflow.G.nodes[producer_name].get("type") == "tool"
                        for producer_name in workflow.G.predecessors(
                            target_artifact
                        )
                    )
                    for target_artifact in target_artifacts
                )

                if not targets_are_produced:
                    continue

                if starting_artifacts and target_artifacts:
                    has_all_paths = all(
                        _has_positive_length_path(
                            workflow.G,
                            start,
                            target,
                        )
                        for start in starting_artifacts
                        for target in target_artifacts
                    )

                    if not has_all_paths:
                        continue

                workflow.starting_artifacts = deepcopy(self.starting_artifacts)
                workflow.target_artifacts = deepcopy(self.target_artifacts)

                workflows.append(workflow)

        return workflows

    def discover_continuation_plans(
        self,
        available_artifacts: Iterable[str],
        anchor_artifacts: Iterable[str],
        target_artifacts: Iterable[str],
    ) -> list[Plan]:
        """Return minimal plans from an observed state to fresh targets.

        ``available_artifacts`` are usable now. ``anchor_artifacts`` identify
        the recent results from which the continuation should proceed. Every
        returned plan reaches each target from at least one anchor; unrelated
        available artifacts do not need to lead to every target.

        A plan may require an artifact that has no producer in this network;
        that artifact remains an external input reported by the plan. When an
        unavailable input does have network producers, at least one producer
        must be included. Strongly connected tool components are selected as
        indivisible units, so cycles remain structural rather than unrolled.

        The search is exhaustive and is intended for bounded tool networks.
        """
        available = self._continuation_boundary(
            "available_artifacts",
            available_artifacts,
            allow_empty=True,
        )
        anchors = self._continuation_boundary(
            "anchor_artifacts",
            anchor_artifacts,
        )
        targets = self._continuation_boundary(
            "target_artifacts",
            target_artifacts,
        )

        known_artifacts = set(self.artifact_names)
        unknown = (
            set(available) | set(anchors) | set(targets)
        ) - known_artifacts
        if unknown:
            raise ValueError(f"Unknown artifacts: {sorted(unknown)}")

        unavailable_anchors = set(anchors) - set(available)
        if unavailable_anchors:
            raise ValueError(
                "anchor_artifacts must already be available: "
                f"{sorted(unavailable_anchors)}"
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
                if self._is_valid_continuation_plan(
                    selected_tools,
                    frozenset(available),
                    anchors,
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
            plan.starting_artifacts = [
                artifact_name
                for artifact_name in anchors
                if artifact_name in plan.artifact_names
            ]
            plan.target_artifacts = list(targets)
            plans.append(plan)
        return plans

    def _is_valid_continuation_plan(
        self,
        selected_tools: frozenset[str],
        available_artifacts: frozenset[str],
        anchor_artifacts: tuple[str, ...],
        target_artifacts: tuple[str, ...],
    ) -> bool:
        """Return whether a tool subset is one complete continuation."""
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

        for tool in selected:
            for artifact in tool.inputs:
                if artifact.name in available_artifacts:
                    continue
                producers = {
                    candidate.name
                    for candidate in self.tools
                    if any(
                        output.name == artifact.name
                        for output in candidate.outputs
                    )
                }
                if producers and not producers & selected_tools:
                    return False

        plan_graph = self._typed_dependency_graph(selected_tools)

        if any(
            not any(
                _has_positive_length_path(
                    plan_graph,
                    ("artifact", anchor),
                    ("artifact", target),
                )
                for anchor in anchor_artifacts
            )
            for target in target_artifacts
        ):
            return False

        return all(
            any(
                nx.has_path(
                    plan_graph,
                    ("tool", tool.name),
                    ("artifact", target),
                )
                for target in target_artifacts
            )
            for tool in selected
        )

    @staticmethod
    def _continuation_boundary(
        name: str,
        artifacts: Iterable[str],
        *,
        allow_empty: bool = False,
    ) -> tuple[str, ...]:
        if isinstance(artifacts, str):
            values = (artifacts,)
        else:
            try:
                values = tuple(artifacts)
            except TypeError:
                raise TypeError(f"{name} must contain artifact names.") from None

        if not all(isinstance(value, str) for value in values):
            raise TypeError(f"{name} must contain artifact names.")
        values = tuple(dict.fromkeys(values))
        if not values and not allow_empty:
            raise ValueError(f"{name} cannot be empty.")
        return values

    def similar_workflows(
        self,
        workflow: Workflow,
        *,
        ignore_identical: bool = False,
    ) -> list[tuple[Workflow, float]]:
        """
        Return discovered workflows ranked by similarity to a workflow.

        All candidates are aligned together in one QAP study so every score
        uses the same node universe. Structurally identical candidates are
        included by default with a score of 1.0.
        """
        if not isinstance(workflow, Workflow):
            raise TypeError("workflow must be a Workflow.")

        if not isinstance(ignore_identical, bool):
            raise TypeError("ignore_identical must be a boolean.")

        candidates = [
            candidate
            for candidate in self.discover()
            if not ignore_identical
            or not nx.utils.graphs_equal(candidate.G, workflow.G)
        ]

        if not candidates:
            return []

        reference_name = "Reference Workflow"
        candidate_names = [
            f"Candidate Workflow {index}"
            for index in range(1, len(candidates) + 1)
        ]
        study = QAPStudy(
            networks={
                reference_name: workflow.G,
                **{
                    name: candidate.G
                    for name, candidate in zip(
                        candidate_names,
                        candidates,
                        strict=True,
                    )
                },
            }
        )

        ranked_workflows = [
            (
                candidate,
                1.0
                if nx.utils.graphs_equal(candidate.G, workflow.G)
                else study.correlation(reference_name, candidate_name),
            )
            for candidate_name, candidate in zip(
                candidate_names,
                candidates,
                strict=True,
            )
        ]
        ranked_workflows.sort(
            key=lambda candidate_and_score: candidate_and_score[1],
            reverse=True,
        )

        return ranked_workflows


if __name__ == "__main__":

    from artifactflow.tool.examples import tool_1, tool_2, tool_3, tool_4

    tool_network = ToolNetwork()
    tool_network.add_tool(tool_1)
    tool_network.add_tool(tool_2)
    tool_network.add_tool(tool_3)
    tool_network.add_tool(tool_4)

    tool_network.show()

    filtered_tool_network = tool_network.filter(exclude_tools=["Tool 4", "Tool 2"])
    filtered_tool_network = filtered_tool_network.filter(starting_artifacts=["Artifact 4"])

    filtered_tool_network.show()

    workflows = filtered_tool_network.discover()
    print(len(workflows))
