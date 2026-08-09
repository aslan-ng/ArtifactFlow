import unittest

import networkx as nx

from artifactflow import (
    Artifact,
    Plan,
    PlanRequirements,
    Tool,
    ToolNetwork,
    Workflow,
)


def make_workflow(
    *tools: Tool,
    starting_artifacts: tuple[str, ...] = ("start",),
    target_artifacts: tuple[str, ...] = ("target",),
) -> Workflow:
    workflow = Workflow()
    for tool in tools:
        workflow.add_tool(tool)
    workflow.starting_artifacts = list(starting_artifacts)
    workflow.target_artifacts = list(target_artifacts)
    return workflow


def discovered_tool_names(workflow: Workflow) -> set[tuple[str, ...]]:
    return {
        tuple(plan.tool_names)
        for plan in workflow.discover_plans()
    }


class TestPlan(unittest.TestCase):
    def test_from_workflow_copies_tools_graph_and_boundaries(self):
        start = Artifact("start")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("A", inputs=[start], outputs=[target]),
        )

        plan = Plan.from_workflow(workflow)

        self.assertIsInstance(plan, Plan)
        self.assertIsNot(plan, workflow)
        self.assertEqual(plan.tool_names, ["A"])
        self.assertTrue(nx.utils.graphs_equal(plan.G, workflow.G))
        self.assertEqual(plan.starting_artifacts, ["start"])
        self.assertEqual(plan.target_artifacts, ["target"])
        self.assertIsNot(
            plan.starting_artifacts,
            workflow.starting_artifacts,
        )
        self.assertIsNot(
            plan.target_artifacts,
            workflow.target_artifacts,
        )
        self.assertTrue(plan.contains_tool("A"))
        self.assertFalse(plan.contains_tool("missing"))

    def test_contains_tool_is_shared_by_every_network_type(self):
        tool = Tool("A")
        workflow = Workflow()
        plan = Plan()
        tool_network = ToolNetwork()

        for network in (workflow, plan, tool_network):
            network.add_tool(tool)
            self.assertTrue(network.contains_tool("A"))
            self.assertFalse(network.contains_tool("missing"))

        with self.assertRaisesRegex(TypeError, "string"):
            workflow.contains_tool(tool)  # type: ignore[arg-type]


class TestWorkflowDiscoverPlans(unittest.TestCase):
    def test_linear_workflow_has_one_plan(self):
        start = Artifact("start")
        middle = Artifact("middle")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("A", inputs=[start], outputs=[middle]),
            Tool("B", inputs=[middle], outputs=[target]),
        )

        self.assertEqual(
            discovered_tool_names(workflow),
            {("A", "B")},
        )

    def test_route_choice_has_two_plans_without_their_union(self):
        start = Artifact("start")
        prepared = Artifact("prepared")
        custom_draft = Artifact("custom draft")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Prepare", inputs=[start], outputs=[prepared]),
            Tool("Quick", inputs=[prepared], outputs=[target]),
            Tool(
                "Custom",
                inputs=[prepared],
                outputs=[custom_draft],
            ),
            Tool(
                "Finish",
                inputs=[custom_draft],
                outputs=[target],
            ),
        )

        self.assertEqual(
            discovered_tool_names(workflow),
            {
                ("Prepare", "Quick"),
                ("Prepare", "Custom", "Finish"),
            },
        )

    def test_join_keeps_every_required_producer_in_one_plan(self):
        start = Artifact("start")
        left = Artifact("left")
        right = Artifact("right")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Make left", inputs=[start], outputs=[left]),
            Tool("Make right", inputs=[start], outputs=[right]),
            Tool("Combine", inputs=[left, right], outputs=[target]),
        )

        self.assertEqual(
            discovered_tool_names(workflow),
            {("Make left", "Make right", "Combine")},
        )

    def test_middle_cycle_is_kept_as_one_repeatable_plan(self):
        brief = Artifact("brief")
        draft = Artifact("draft")
        review = Artifact("review")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Write", inputs=[brief], outputs=[draft]),
            Tool("Review", inputs=[draft], outputs=[review]),
            Tool("Revise", inputs=[review], outputs=[draft]),
            Tool("Publish", inputs=[review], outputs=[target]),
            starting_artifacts=("brief",),
        )

        self.assertEqual(
            discovered_tool_names(workflow),
            {("Write", "Review", "Revise", "Publish")},
        )

    def test_target_producing_cycle_is_one_plan(self):
        brief = Artifact("brief")
        draft = Artifact("draft")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Write", inputs=[brief], outputs=[draft]),
            Tool(
                "Evaluate",
                inputs=[draft],
                outputs=[brief, target],
            ),
            starting_artifacts=("brief",),
        )

        self.assertEqual(
            discovered_tool_names(workflow),
            {("Write", "Evaluate")},
        )

    def test_missing_starting_boundary_is_rejected(self):
        target = Artifact("target")
        workflow = Workflow()
        workflow.add_tool(Tool("A", outputs=[target]))
        workflow.target_artifacts = ["target"]

        with self.assertRaisesRegex(ValueError, "starting_artifacts"):
            workflow.discover_plans()

    def test_missing_target_boundary_is_rejected(self):
        start = Artifact("start")
        workflow = Workflow()
        workflow.add_tool(Tool("A", inputs=[start]))
        workflow.starting_artifacts = ["start"]

        with self.assertRaisesRegex(ValueError, "target_artifacts"):
            workflow.discover_plans()

    def test_boundaries_can_be_provided_to_plan_discovery(self):
        start = Artifact("start")
        target = Artifact("target")
        workflow = Workflow()
        workflow.add_tool(Tool("A", inputs=[start], outputs=[target]))

        plans = workflow.discover_plans(
            starting_artifacts=["start"],
            target_artifacts=["target"],
        )

        self.assertEqual([plan.tool_names for plan in plans], [["A"]])


class TestPlanInputRequirements(unittest.TestCase):
    def test_linear_plan_requires_its_external_input(self):
        start = Artifact("start")
        middle = Artifact("middle")
        target = Artifact("target")
        plan = Plan.from_workflow(make_workflow(
            Tool("A", inputs=[start], outputs=[middle]),
            Tool("B", inputs=[middle], outputs=[target]),
        ))

        requirements = plan.input_requirements()

        self.assertIsInstance(requirements, PlanRequirements)
        self.assertEqual(requirements.external_artifacts, {"start"})
        self.assertEqual(requirements.bootstrap_artifacts, set())
        self.assertEqual(requirements.initial_artifacts, {"start"})
        self.assertFalse(requirements.is_satisfied)

    def test_target_cycle_requires_a_bootstrap_seed(self):
        brief = Artifact("brief")
        draft = Artifact("draft")
        target = Artifact("target")
        plan = Plan.from_workflow(make_workflow(
            Tool("Write", inputs=[brief], outputs=[draft]),
            Tool(
                "Evaluate",
                inputs=[draft],
                outputs=[brief, target],
            ),
            starting_artifacts=("brief",),
        ))

        requirements = plan.input_requirements()

        self.assertEqual(requirements.external_artifacts, set())
        self.assertEqual(requirements.bootstrap_artifacts, {"brief"})
        self.assertEqual(requirements.initial_artifacts, {"brief"})
        self.assertFalse(requirements.is_satisfied)

    def test_external_input_can_be_required_by_only_one_route_plan(self):
        request = Artifact("request")
        prepared = Artifact("prepared")
        template = Artifact("template")
        custom_draft = Artifact("custom draft")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("Prepare", inputs=[request], outputs=[prepared]),
            Tool(
                "Quick",
                inputs=[prepared, template],
                outputs=[target],
            ),
            Tool(
                "Custom",
                inputs=[prepared],
                outputs=[custom_draft],
            ),
            Tool(
                "Finish",
                inputs=[custom_draft],
                outputs=[target],
            ),
            starting_artifacts=("request",),
        )
        plans = {
            tuple(plan.tool_names): plan
            for plan in workflow.discover_plans()
        }

        quick = plans[("Prepare", "Quick")].input_requirements()
        custom = plans[("Prepare", "Custom", "Finish")].input_requirements()

        self.assertEqual(
            quick.external_artifacts,
            {"request", "template"},
        )
        self.assertEqual(custom.external_artifacts, {"request"})
        self.assertNotIn("template", custom.initial_artifacts)

    def test_available_artifacts_are_removed_only_from_missing_requirements(self):
        request = Artifact("request")
        template = Artifact("template")
        target = Artifact("target")
        plan = Plan.from_workflow(make_workflow(
            Tool(
                "Create",
                inputs=[request, template],
                outputs=[target],
            ),
            starting_artifacts=("request",),
        ))
        full_requirements = plan.input_requirements()

        missing = plan.missing_input_requirements({"request"})

        self.assertEqual(missing.external_artifacts, {"template"})
        self.assertEqual(missing.bootstrap_artifacts, set())
        self.assertEqual(missing.initial_artifacts, {"template"})
        self.assertFalse(missing.is_satisfied)
        self.assertEqual(
            missing,
            full_requirements.missing({"request"}),
        )
        self.assertEqual(
            plan.input_requirements(),
            full_requirements,
        )
        self.assertEqual(
            full_requirements.external_artifacts,
            {"request", "template"},
        )

        satisfied = plan.missing_input_requirements(
            {"request", "template"}
        )
        self.assertTrue(satisfied.is_satisfied)
        self.assertEqual(satisfied.initial_artifacts, set())

    def test_nested_downstream_cycle_requires_its_internal_seed(self):
        start = Artifact("start")
        ready = Artifact("ready")
        state = Artifact("state")
        result = Artifact("result")
        target = Artifact("target")
        plan = Plan.from_workflow(make_workflow(
            Tool("Prepare", inputs=[start], outputs=[ready]),
            Tool(
                "Analyze",
                inputs=[ready, state],
                outputs=[result],
            ),
            Tool("Update", inputs=[result], outputs=[state]),
            Tool("Finish", inputs=[result], outputs=[target]),
        ))

        requirements = plan.input_requirements()

        self.assertEqual(requirements.external_artifacts, {"start"})
        self.assertEqual(requirements.bootstrap_artifacts, {"state"})
        self.assertEqual(
            requirements.initial_artifacts,
            {"start", "state"},
        )
        self.assertTrue(
            plan.missing_input_requirements(
                {"start", "state"}
            ).is_satisfied
        )

    def test_cycle_bootstrap_is_a_minimal_seed_set(self):
        start = Artifact("start")
        x = Artifact("x")
        y = Artifact("y")
        z = Artifact("z")
        target = Artifact("target")
        plan = Plan.from_workflow(make_workflow(
            Tool(
                "A",
                inputs=[start, x, y],
                outputs=[z, target],
            ),
            Tool("B", inputs=[z], outputs=[x]),
            Tool("C", inputs=[x], outputs=[y]),
        ))

        requirements = plan.input_requirements()

        self.assertEqual(requirements.external_artifacts, {"start"})
        self.assertEqual(requirements.bootstrap_artifacts, {"x"})

    def test_declared_start_resolves_alternative_cycle_seeds(self):
        x = Artifact("x")
        y = Artifact("y")
        target = Artifact("target")
        plan = Plan.from_workflow(make_workflow(
            Tool("A", inputs=[x], outputs=[y]),
            Tool("B", inputs=[y], outputs=[x, target]),
            starting_artifacts=("y",),
        ))

        self.assertEqual(
            plan.input_requirements().bootstrap_artifacts,
            {"y"},
        )


class TestWorkflowToolNetworkConversion(unittest.TestCase):
    def test_to_tool_network_copies_exact_graph_and_boundaries(self):
        start = Artifact("start")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("A", inputs=[start], outputs=[target]),
        )

        tool_network = workflow.to_tool_network()

        self.assertIsInstance(tool_network, ToolNetwork)
        self.assertIsNot(tool_network, workflow)
        self.assertEqual(tool_network.tool_names, workflow.tool_names)
        self.assertTrue(nx.utils.graphs_equal(tool_network.G, workflow.G))
        self.assertEqual(tool_network.starting_artifacts, ["start"])
        self.assertEqual(tool_network.target_artifacts, ["target"])
        self.assertIsNot(
            tool_network.starting_artifacts,
            workflow.starting_artifacts,
        )
        self.assertIsNot(
            tool_network.target_artifacts,
            workflow.target_artifacts,
        )

    def test_tool_network_contains_an_exact_workflow(self):
        start = Artifact("start")
        middle = Artifact("middle")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("A", inputs=[start], outputs=[middle]),
            Tool("B", inputs=[middle], outputs=[target]),
        )

        self.assertTrue(workflow.to_tool_network().contains_workflow(workflow))

    def test_tool_network_does_not_contain_a_missing_workflow_tool(self):
        start = Artifact("start")
        middle = Artifact("middle")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("A", inputs=[start], outputs=[middle]),
            Tool("B", inputs=[middle], outputs=[target]),
        )
        tool_network = ToolNetwork()
        tool_network.add_tool(workflow.tools[0])

        self.assertFalse(tool_network.contains_workflow(workflow))

    def test_same_tool_name_with_different_schema_is_not_contained(self):
        start = Artifact("start")
        target = Artifact("target")
        different_target = Artifact("different target")
        workflow = make_workflow(
            Tool("A", inputs=[start], outputs=[target]),
        )
        tool_network = ToolNetwork()
        tool_network.add_tool(
            Tool("A", inputs=[start], outputs=[different_target])
        )

        self.assertFalse(tool_network.contains_workflow(workflow))


if __name__ == "__main__":
    unittest.main()
