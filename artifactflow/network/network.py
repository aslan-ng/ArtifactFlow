from __future__ import annotations
import networkx as nx

from artifactflow.tool import Tool
from artifactflow.network.graphics import Graphics


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
        return [
            node
            for node, data in self.G.nodes(data=True)
            if data.get("type") == "artifact"
        ]

    def producer_conflicts(self) -> dict[str, list[str]]:
        """
        Return artifacts produced by more than one tool.

        Artifact and producer ordering follows their insertion order in the
        network.
        """
        conflicts = {}

        for node, data in self.G.nodes(data=True):
            if data["type"] != "artifact":
                continue

            producer_names = {
                predecessor
                for predecessor in self.G.predecessors(node)
                if self.G.nodes[predecessor]["type"] == "tool"
            }

            if len(producer_names) < 2:
                continue

            conflicts[node] = [
                tool.name
                for tool in self.tools
                if tool.name in producer_names
            ]

        return conflicts

    def has_producer_conflicts(self) -> bool:
        """Return whether any artifact has more than one producer tool."""
        return bool(self.producer_conflicts())

    def add_tool(self, tool: Tool):
        if tool.name in self.tool_names:
            raise ValueError(f"Tool with name {tool.name} already exists in the workflow.")
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

    network.show()
