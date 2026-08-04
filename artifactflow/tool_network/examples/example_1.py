"""
Tool Network (without any filtering)
"""

from artifactflow.tool_network import ToolNetwork
from artifactflow.tool.examples import tool_1, tool_2, tool_3, tool_4


tools = [tool_1, tool_2, tool_3, tool_4]
tool_network = ToolNetwork()
for tool in tools:
    tool_network.add_tool(tool)


if __name__ == "__main__":
    tool_network.show()