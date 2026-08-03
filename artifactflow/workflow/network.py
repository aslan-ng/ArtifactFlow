from __future__ import annotations
import networkx as nx

from artifactflow.tool import Tool
from artifactflow.workflow.graphics import Graphics


class Network(
    Graphics,
):

    def __init__(
        self,
    ):
        self.tools = []
        self.G = nx.DiGraph()

    @property
    def tool_names(self):
        return [tool.name for tool in self.tools]

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

    tool_network = Network()
    tool_network.add_tool(tool_1)
    tool_network.add_tool(tool_2)
    tool_network.add_tool(tool_3)
    tool_network.add_tool(tool_4)

    tool_network.show()