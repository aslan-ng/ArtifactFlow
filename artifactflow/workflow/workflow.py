import networkx as nx

from artifactflow.workflow.network import Network


class Workflow(
    Network,
):
    pass
        

if __name__ == "__main__":

    from artifactflow.tool.examples import tool_1, tool_2, tool_3, tool_4

    tool_network = Workflow()
    tool_network.add_tool(tool_1)
    tool_network.add_tool(tool_2)
    tool_network.add_tool(tool_3)
    tool_network.add_tool(tool_4)

    tool_network.show()