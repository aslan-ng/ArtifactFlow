import unittest

import networkx as nx

from artifactflow import Artifact, Tool, ToolNetwork, Workflow


def middle_cycle_tools() -> tuple[Tool, ...]:
    brief = Artifact("brief")
    draft = Artifact("draft")
    review = Artifact("review")
    target = Artifact("target")
    return (
        Tool("setup", inputs=[brief], outputs=[draft]),
        Tool("review", inputs=[draft], outputs=[review]),
        Tool("revise", inputs=[review], outputs=[draft]),
        Tool("publish", inputs=[review], outputs=[target]),
    )


def make_workflow() -> Workflow:
    workflow = Workflow()
    for tool in middle_cycle_tools():
        workflow.add_tool(tool)
    workflow.starting_artifacts = ["brief"]
    workflow.target_artifacts = ["target"]
    return workflow


def make_tool_network() -> ToolNetwork:
    network = ToolNetwork()
    for tool in middle_cycle_tools():
        network.add_tool(tool)
    return network


class TestToolArtifactNameCollisions(unittest.TestCase):
    def test_artifact_and_tool_names_are_both_retained(self):
        workflow = make_workflow()

        self.assertIn("review", workflow.tool_names)
        self.assertIn("review", workflow.artifact_names)
        self.assertEqual(
            workflow.artifact_names,
            ["brief", "draft", "review", "target"],
        )

    def test_tool_projection_keeps_the_cycle_when_names_collide(self):
        graph = make_workflow().to_tool_dependency_graph()

        self.assertEqual(
            set(graph.edges),
            {
                ("setup", "review"),
                ("review", "revise"),
                ("review", "publish"),
                ("revise", "review"),
            },
        )
        self.assertIn(
            {"review", "revise"},
            [
                set(component)
                for component in nx.strongly_connected_components(graph)
            ],
        )

    def test_workflow_plan_discovery_keeps_the_cycle_atomic(self):
        plans = make_workflow().discover_plans()

        self.assertEqual(len(plans), 1)
        self.assertEqual(
            plans[0].tool_names,
            ["setup", "review", "revise", "publish"],
        )
        self.assertEqual(
            plans[0].input_requirements().external_artifacts,
            {"brief"},
        )

    def test_continuation_plan_discovery_keeps_the_cycle_atomic(self):
        plans = make_tool_network().discover_continuation_plans(
            available_artifacts=["brief"],
            anchor_artifacts=["brief"],
            target_artifacts=["target"],
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(
            plans[0].tool_names,
            ["setup", "review", "revise", "publish"],
        )
        self.assertEqual(plans[0].starting_artifacts, ["brief"])
        self.assertEqual(plans[0].target_artifacts, ["target"])


if __name__ == "__main__":
    unittest.main()
