from __future__ import annotations

import networkx as nx

from artifactflow.tool import Tool


class Workflow:

    def __init__(self, name: str | None = None):
        self.name = name
        self.G = nx.DiGraph()

    @staticmethod
    def tool_node(tool: Tool) -> tuple[str, str]:
        return ("tool", tool.name)

    @staticmethod
    def artifact_node(
        producer: Tool,
        artifact_name: str,
    ) -> tuple[str, str, str]:
        return (
            "artifact",
            producer.name,
            artifact_name,
        )

    @property
    def tools(self) -> list[Tool]:
        return [
            data["tool"]
            for _, data in self.G.nodes(data=True)
            if data["type"] == "tool"
        ]

    @property
    def tool_names(self) -> list[str]:
        return [
            tool.name
            for tool in self.tools
        ]

    def add_tool(self, tool: Tool) -> None:
        if tool.name in self.tool_names:
            raise ValueError(
                f"Tool {tool.name!r} already exists "
                "in the workflow."
            )

        tool_node = self.tool_node(tool)

        self.G.add_node(
            tool_node,
            type="tool",
            tool=tool,
            label=tool.name,
        )

        # Create the artifacts produced by this tool.
        for artifact in tool.outputs:
            artifact_node = self.artifact_node(
                producer=tool,
                artifact_name=artifact.name,
            )

            self.G.add_node(
                artifact_node,
                type="artifact",
                artifact=artifact,
                label=artifact.name,
                producer=tool.name,
            )

            self.G.add_edge(
                tool_node,
                artifact_node,
                type="output",
            )

    def connect_tools(
        self,
        tool_from: Tool,
        tool_to: Tool,
    ) -> list[str]:
        tool_from_node = self.tool_node(tool_from)
        tool_to_node = self.tool_node(tool_to)

        if tool_from_node not in self.G:
            raise ValueError(
                f"Tool {tool_from.name!r} is not "
                "in the workflow."
            )

        if tool_to_node not in self.G:
            raise ValueError(
                f"Tool {tool_to.name!r} is not "
                "in the workflow."
            )

        if tool_from_node == tool_to_node:
            raise ValueError(
                "A tool cannot connect to itself."
            )

        output_names = {
            artifact.name
            for artifact in tool_from.outputs
        }

        input_names = {
            artifact.name
            for artifact in tool_to.inputs
        }

        shared_artifacts = sorted(
            output_names & input_names
        )

        if not shared_artifacts:
            raise ValueError(
                f"{tool_from.name!r} does not produce "
                f"an input required by {tool_to.name!r}."
            )

        # Feedback and cycles are rejected for now.
        if nx.has_path(
            self.G,
            tool_to_node,
            tool_from_node,
        ):
            raise ValueError(
                f"Connecting {tool_from.name!r} to "
                f"{tool_to.name!r} would create a cycle."
            )

        for artifact_name in shared_artifacts:
            artifact_node = self.artifact_node(
                producer=tool_from,
                artifact_name=artifact_name,
            )

            self.G.add_edge(
                artifact_node,
                tool_to_node,
                type="input",
            )

        return shared_artifacts

    def missing_inputs(
        self,
        tool: Tool,
    ) -> list:
        tool_node = self.tool_node(tool)

        if tool_node not in self.G:
            raise ValueError(
                f"Tool {tool.name!r} is not "
                "in the workflow."
            )

        connected_input_names = {
            self.G.nodes[node]["artifact"].name
            for node in self.G.predecessors(tool_node)
            if self.G.nodes[node]["type"] == "artifact"
        }

        return [
            artifact
            for artifact in tool.inputs
            if artifact.name not in connected_input_names
        ]

    @property
    def is_acyclic(self) -> bool:
        return nx.is_directed_acyclic_graph(self.G)