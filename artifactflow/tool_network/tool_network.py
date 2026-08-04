from __future__ import annotations

from itertools import combinations
import networkx as nx
from copy import deepcopy

from artifactflow.similarity.qap import QAPStudy
from artifactflow.network.network import Network
from artifactflow.workflow.workflow import Workflow


def _has_positive_length_path(
    graph: nx.DiGraph,
    start: str,
    target: str,
) -> bool:
    """Return whether a directed path traverses at least one edge."""
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
