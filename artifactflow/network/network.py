from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
from numpy.typing import NDArray

from artifactflow.tool import Tool
from artifactflow.network.graphics import Graphics


@dataclass(frozen=True, slots=True)
class ToolDependencyMatrix:
    """A tool DSM together with its shared row and column labels."""

    matrix: NDArray[np.int64]
    tool_names: tuple[str, ...]

    @property
    def tool_indices(self) -> dict[str, int]:
        """Return each tool's row and column index in the matrix."""
        return {
            tool_name: index
            for index, tool_name in enumerate(self.tool_names)
        }


class Network(
    Graphics,
):
    """
    Super class for Workflow and ToolNetwork classes.
    """

    def __init__(
        self,
    ):
        self.tools = []
        self.G = nx.DiGraph()

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    @property
    def artifact_names(self) -> list[str]:
        """Return artifact names independently of display-graph node keys."""
        return list(dict.fromkeys(
            artifact.name
            for tool in self.tools
            for artifact in (*tool.inputs, *tool.outputs)
        ))

    def contains_tool(self, tool_name: str) -> bool:
        """Return whether this network contains a named tool."""
        if not isinstance(tool_name, str):
            raise TypeError("tool_name must be a string.")
        return tool_name in self.tool_names

    def to_tool_dependency_graph(self) -> nx.DiGraph:
        """
        Return a tool-only projection of the artifact dependency graph.

        Each edge points from an artifact producer to an artifact consumer.
        When several artifacts connect the same two tools, their names are
        stored together in the edge's ``artifacts`` attribute.
        """
        tool_graph = nx.DiGraph()
        tool_graph.add_nodes_from(
            (
                tool.name,
                {"type": "tool"},
            )
            for tool in self.tools
        )

        for artifact_name in self.artifact_names:
            producer_names = [
                tool.name
                for tool in self.tools
                if any(
                    artifact.name == artifact_name
                    for artifact in tool.outputs
                )
            ]
            consumer_names = [
                tool.name
                for tool in self.tools
                if any(
                    artifact.name == artifact_name
                    for artifact in tool.inputs
                )
            ]

            for producer_name in producer_names:
                for consumer_name in consumer_names:
                    if tool_graph.has_edge(producer_name, consumer_name):
                        tool_graph[producer_name][consumer_name][
                            "artifacts"
                        ].append(artifact_name)
                    else:
                        tool_graph.add_edge(
                            producer_name,
                            consumer_name,
                            artifacts=[artifact_name],
                        )

        return tool_graph

    def _typed_dependency_graph(
        self,
        tool_names: frozenset[str] | set[str] | None = None,
    ) -> nx.DiGraph:
        """Return a bipartite graph whose typed keys cannot collide.

        ``G`` remains the package's concise public/display graph and uses
        plain names as node keys. Structural analysis uses this private graph
        so a tool and artifact may safely have the same public name.
        """
        selected_names = (
            set(self.tool_names)
            if tool_names is None
            else set(tool_names)
        )
        graph = nx.DiGraph()

        for tool in self.tools:
            if tool.name not in selected_names:
                continue

            tool_node = ("tool", tool.name)
            graph.add_node(tool_node, type="tool", name=tool.name)
            for artifact in tool.inputs:
                artifact_node = ("artifact", artifact.name)
                graph.add_node(
                    artifact_node,
                    type="artifact",
                    name=artifact.name,
                )
                graph.add_edge(artifact_node, tool_node, type="input")
            for artifact in tool.outputs:
                artifact_node = ("artifact", artifact.name)
                graph.add_node(
                    artifact_node,
                    type="artifact",
                    name=artifact.name,
                )
                graph.add_edge(tool_node, artifact_node, type="output")

        return graph

    def to_tool_dependency_matrix(self) -> ToolDependencyMatrix:
        """
        Return the tool design structure matrix (DSM).

        Rows and columns follow ``tool_names`` order. A value at
        ``matrix[producer, consumer]`` is one when the row tool supplies at
        least one artifact to the column tool, and zero otherwise. The
        diagonal is always one. With tools in execution order, feedforward
        dependencies appear above the diagonal and feedback dependencies
        appear below it.
        """
        tool_graph = self.to_tool_dependency_graph()
        tool_names = tuple(self.tool_names)
        tool_indices = {
            tool_name: index
            for index, tool_name in enumerate(tool_names)
        }
        matrix = np.zeros(
            (len(tool_names), len(tool_names)),
            dtype=np.int64,
        )

        for producer_name, consumer_name in tool_graph.edges:
            matrix[
                tool_indices[producer_name],
                tool_indices[consumer_name],
            ] = 1

        np.fill_diagonal(matrix, 1)

        return ToolDependencyMatrix(
            matrix=matrix,
            tool_names=tool_names,
        )

    def producer_conflicts(self) -> dict[str, list[str]]:
        """
        Return artifacts produced by more than one tool.

        Artifact and producer ordering follows their insertion order in the
        network.
        """
        conflicts = {}

        for artifact_name in self.artifact_names:
            producer_names = {
                tool.name
                for tool in self.tools
                if any(
                    artifact.name == artifact_name
                    for artifact in tool.outputs
                )
            }

            if len(producer_names) < 2:
                continue

            conflicts[artifact_name] = [
                tool.name
                for tool in self.tools
                if tool.name in producer_names
            ]

        return conflicts

    def has_producer_conflicts(self) -> bool:
        """
        Return whether any artifact has more than one producer tool.
        """
        return bool(self.producer_conflicts())

    def add_tool(self, tool: Tool):
        if tool.name in self.tool_names:
            raise ValueError(
                f"Tool with name {tool.name} already exists in the network."
            )
        self.tools.append(tool)
        self.G.add_node(tool.name, type='tool')

        for artifact in tool.inputs:
            self.G.add_node(artifact.name, type='artifact')
            self.G.add_edge(artifact.name, tool.name, type='input')

        for artifact in tool.outputs:
            self.G.add_node(artifact.name, type='artifact')
            self.G.add_edge(tool.name, artifact.name, type='output')

    def remove_tool(self, tool_name: str) -> None:
        if tool_name not in self.tool_names:
            raise ValueError(
                f"Tool with name {tool_name} does not exist in the network."
            )

        artifacts = set(self.G.predecessors(tool_name))
        artifacts.update(self.G.successors(tool_name))

        self.tools = [
            tool
            for tool in self.tools
            if tool.name != tool_name
        ]

        # NetworkX automatically removes the tool's edges.
        self.G.remove_node(tool_name)

        # Remove artifacts that are no longer connected to any tool.
        for artifact in artifacts:
            if self.G.degree(artifact) == 0:
                self.G.remove_node(artifact)
        

if __name__ == "__main__":

    from artifactflow.tool.examples import tool_1, tool_2, tool_3, tool_4

    network = Network()
    network.add_tool(tool_1)
    network.add_tool(tool_2)
    network.add_tool(tool_3)
    network.add_tool(tool_4)

    print(network.producer_conflicts())
    dsm = network.to_tool_dependency_matrix()
    print(dsm.matrix, dsm.tool_names)

    network.show()
