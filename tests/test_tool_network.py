import unittest

import networkx as nx

from artifactflow.artifact.artifact import Artifact
from artifactflow.tool.tool import Tool
from artifactflow.workflow.tool_network import ToolNetwork
from artifactflow.workflow.workflow import Workflow


def make_tool_network(*tools: Tool) -> ToolNetwork:
    network = ToolNetwork()
    for tool in tools:
        network.add_tool(tool)
    return network


class TestToolNetworkDiscover(unittest.TestCase):
    def setUp(self):
        shared = Artifact("shared")
        isolated_input = Artifact("isolated input")
        isolated_output = Artifact("isolated output")

        self.tool_a = Tool("A", outputs=[shared])
        self.tool_b = Tool("B", inputs=[shared])
        self.tool_c = Tool(
            "C",
            inputs=[isolated_input],
            outputs=[isolated_output],
        )

    def test_returns_every_connected_tool_subset_largest_first(self):
        network = make_tool_network(self.tool_a, self.tool_b, self.tool_c)

        workflows = network.discover()

        self.assertEqual(
            [workflow.tool_names for workflow in workflows],
            [["A", "B"], ["A"], ["B"], ["C"]],
        )
        self.assertTrue(
            all(isinstance(workflow, Workflow) for workflow in workflows)
        )
        self.assertTrue(
            all(nx.is_weakly_connected(workflow.G) for workflow in workflows)
        )

    def test_full_network_is_first_when_connected(self):
        network = make_tool_network(self.tool_a, self.tool_b)

        workflows = network.discover()

        self.assertEqual(workflows[0].tool_names, network.tool_names)
        self.assertTrue(nx.utils.graphs_equal(workflows[0].G, network.G))
        self.assertIsNot(workflows[0], network)

    def test_empty_network_has_no_workflows(self):
        self.assertEqual(ToolNetwork().discover(), [])

    def test_remembered_artifact_filters_apply_to_discovery(self):
        start = Artifact("start")
        middle = Artifact("middle")
        target = Artifact("target")
        first = Tool("first", inputs=[start], outputs=[middle])
        second = Tool("second", inputs=[middle], outputs=[target])
        network = make_tool_network(first, second)

        filtered = network.filter(
            starting_artifacts=["start"],
            target_artifacts=["target"],
        )

        self.assertEqual(
            [workflow.tool_names for workflow in filtered.discover()],
            [["first", "second"]],
        )

    def test_remembered_start_filter_rejects_downstream_subsets(self):
        start = Artifact("start")
        middle = Artifact("middle")
        target = Artifact("target")
        first = Tool("first", inputs=[start], outputs=[middle])
        second = Tool("second", inputs=[middle], outputs=[target])
        network = make_tool_network(first, second)

        filtered = network.filter(starting_artifacts=["start"])

        self.assertEqual(
            [workflow.tool_names for workflow in filtered.discover()],
            [["first", "second"], ["first"]],
        )

    def test_remembered_included_tools_are_present_in_every_workflow(self):
        network = make_tool_network(self.tool_a, self.tool_b)

        filtered = network.filter(include_tools=["A", "B"])

        self.assertEqual(
            [workflow.tool_names for workflow in filtered.discover()],
            [["A", "B"]],
        )


if __name__ == "__main__":
    unittest.main()
