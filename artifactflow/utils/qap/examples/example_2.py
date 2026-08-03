from artifactflow.utils.qap.qap import QAPStudy
from artifactflow.tool.tool_network import ToolNetwork
from artifactflow.tool.examples import (
    tool_1,
    tool_2,
    tool_3,
    tool_4,
)


"""Tool Network 1"""

tool_network_1 = ToolNetwork()
tool_network_1.add_tool(tool_1)
tool_network_1.add_tool(tool_2)
tool_network_1.add_tool(tool_3)
tool_network_1.add_tool(tool_4)


"""Tool Network 2"""

tool_network_2 = ToolNetwork()
tool_network_2.add_tool(tool_1)
tool_network_2.add_tool(tool_2)
tool_network_2.add_tool(tool_3)


"""Tool Network 3"""

tool_network_3 = ToolNetwork()
tool_network_3.add_tool(tool_1)
tool_network_3.add_tool(tool_4)


"""Align all networks to the same global node universe"""

study = QAPStudy(
    networks={
        "Tool Network 1": tool_network_1.G,
        "Tool Network 2": tool_network_2.G,
        "Tool Network 3": tool_network_3.G,
    },
    permutations=10_000,
    alternative="two-sided",
    random_state=42,
)

for comparison in study.compare_all():
    comparison.print_summary()