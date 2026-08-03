import networkx as nx

from artifactflow.workflow.network import Network
from artifactflow.workflow.workflow import Workflow


class ToolNetwork(
    Network,
):

    def workflow_from_tools(
        self,
        include_tool_names: list[str] | None = None,
        exclude_tool_names: list[str] | None = None,
    ) -> Workflow:
        available_names = {
            str(tool.name)
            for tool in self.tools
        }

        include_names = (
            set(include_tool_names)
            if include_tool_names is not None
            else available_names
        )

        exclude_names = set(
            exclude_tool_names or []
        )

        unknown_names = (
            include_names | exclude_names
        ) - available_names

        if unknown_names:
            raise ValueError(
                f"Unknown tools: {sorted(unknown_names)}"
            )

        if include_tool_names is not None:
            conflicting_names = (
                include_names & exclude_names
            )

            if conflicting_names:
                raise ValueError(
                    "Tools cannot be both included and excluded: "
                    f"{sorted(conflicting_names)}"
                )

        selected_names = (
            include_names - exclude_names
        )

        if not selected_names:
            raise ValueError(
                "No tools remain in the workflow."
            )

        selected_tools = [
            tool
            for tool in self.tools
            if tool.name in selected_names
        ]

        workflow = Workflow()

        for tool in selected_tools:
            workflow.add_tool(tool)

        if not nx.is_weakly_connected(workflow.G):
            raise ValueError(
                "The selected tools create disconnected processes."
            )

        return workflow
        

if __name__ == "__main__":

    from artifactflow.tool.examples import tool_1, tool_2, tool_3, tool_4

    tool_network = ToolNetwork()
    tool_network.add_tool(tool_1)
    tool_network.add_tool(tool_2)
    tool_network.add_tool(tool_3)
    tool_network.add_tool(tool_4)

    tool_network.show()

    workflow = tool_network.workflow_from_tools(exclude_tool_names=["Tool 4"])

    workflow.show()