import unittest

import networkx as nx

from artifactflow import Artifact, Plan, Project, Tool, ToolNetwork, Workflow


def make_workflow(*tools: Tool) -> Workflow:
    workflow = Workflow()
    for tool in tools:
        workflow.add_tool(tool)
    workflow.starting_artifacts = ["Start"]
    workflow.target_artifacts = ["Target"]
    return workflow


def make_tool_network(*tools: Tool) -> ToolNetwork:
    tool_network = ToolNetwork()
    for tool in tools:
        tool_network.add_tool(tool)
    return tool_network


class TestProjectToolNetwork(unittest.TestCase):
    def setUp(self):
        self.start = Artifact("Start")
        self.middle = Artifact("Middle")
        self.target = Artifact("Target")
        self.network_input = Artifact("Network input")
        self.network_output = Artifact("Network output")

        self.prepare = Tool(
            "Prepare",
            inputs=[self.start],
            outputs=[self.middle],
        )
        self.finish = Tool(
            "Finish",
            inputs=[self.middle],
            outputs=[self.target],
        )
        self.explore = Tool(
            "Explore",
            inputs=[self.network_input],
            outputs=[self.network_output],
        )
        self.workflow = make_workflow(self.prepare, self.finish)

    def test_default_tool_network_is_an_exact_distinct_copy(self):
        project = Project(self.workflow)

        self.assertIsInstance(project.tool_network, ToolNetwork)
        self.assertIsNot(project.tool_network, self.workflow)
        self.assertEqual(
            project.tool_network.tool_names,
            self.workflow.tool_names,
        )
        self.assertTrue(
            nx.utils.graphs_equal(
                project.tool_network.G,
                self.workflow.G,
            )
        )
        self.assertEqual(
            project.tool_network.starting_artifacts,
            self.workflow.starting_artifacts,
        )
        self.assertEqual(
            project.tool_network.target_artifacts,
            self.workflow.target_artifacts,
        )

    def test_accepts_a_supplied_network_that_contains_the_workflow(self):
        tool_network = make_tool_network(
            self.prepare,
            self.finish,
            self.explore,
        )

        project = Project(
            self.workflow,
            tool_network=tool_network,
        )

        self.assertIs(project.tool_network, tool_network)

    def test_rejects_a_network_missing_a_workflow_tool(self):
        incomplete_network = make_tool_network(self.prepare, self.explore)

        with self.assertRaisesRegex(ValueError, "contain.*workflow"):
            Project(
                self.workflow,
                tool_network=incomplete_network,
            )

    def test_rejects_a_same_named_tool_with_a_conflicting_schema(self):
        conflicting_finish = Tool(
            "Finish",
            inputs=[self.middle],
            outputs=[Artifact("Different output")],
        )
        conflicting_network = make_tool_network(
            self.prepare,
            conflicting_finish,
            self.explore,
        )

        with self.assertRaisesRegex(ValueError, "contain.*workflow"):
            Project(
                self.workflow,
                tool_network=conflicting_network,
            )

    def test_records_success_of_a_network_tool_outside_the_workflow(self):
        tool_network = make_tool_network(
            self.prepare,
            self.finish,
            self.explore,
        )
        project = Project(self.workflow, tool_network=tool_network)

        event = project.record_tool_success("Explore")

        self.assertEqual(event.tool_name, "Explore")
        self.assertEqual(
            tuple(item.artifact_name for item in event.inputs),
            ("Network input",),
        )
        self.assertEqual(
            tuple(item.artifact_name for item in event.outputs),
            ("Network output",),
        )
        self.assertEqual(project.state.successful_tools, ("Explore",))
        self.assertIn("Network output", project.available_artifacts)

    def test_records_an_artifact_known_only_to_the_tool_network(self):
        tool_network = make_tool_network(
            self.prepare,
            self.finish,
            self.explore,
        )
        project = Project(self.workflow, tool_network=tool_network)

        artifact = project.record_artifact_available(
            "Network input",
            value="observed value",
        )

        self.assertIs(project.latest_artifact("Network input"), artifact)
        self.assertEqual(artifact.value, "observed value")

    def test_classifies_actions_by_the_narrowest_containing_scope(self):
        tool_network = make_tool_network(
            self.prepare,
            self.finish,
            self.explore,
        )
        project = Project(self.workflow, tool_network=tool_network)
        proposed_plan = Plan()
        proposed_plan.add_tool(self.prepare)

        self.assertEqual(
            project.classify_action("Prepare", (proposed_plan,)),
            "PROPOSED_PLAN",
        )
        self.assertEqual(
            project.classify_action("Finish", (proposed_plan,)),
            "WORKFLOW",
        )
        self.assertEqual(
            project.classify_action("Explore", (proposed_plan,)),
            "TOOL_NETWORK",
        )

    def test_rejects_classifying_a_tool_outside_the_tool_network(self):
        tool_network = make_tool_network(
            self.prepare,
            self.finish,
            self.explore,
        )
        project = Project(self.workflow, tool_network=tool_network)

        with self.assertRaisesRegex(ValueError, "Unknown tool"):
            project.classify_action("Invented tool", ())


if __name__ == "__main__":
    unittest.main()
