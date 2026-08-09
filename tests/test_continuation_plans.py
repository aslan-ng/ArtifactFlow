import unittest

from artifactflow import Artifact, Tool, ToolNetwork


def make_network(*tools: Tool) -> ToolNetwork:
    network = ToolNetwork()
    for tool in tools:
        network.add_tool(tool)
    return network


def tool_sets(plans) -> set[tuple[str, ...]]:
    return {
        tuple(plan.tool_names)
        for plan in plans
    }


class TestContinuationPlanDiscovery(unittest.TestCase):
    def test_continues_from_current_artifact_without_repeating_its_producer(
        self,
    ):
        start = Artifact("start")
        middle = Artifact("middle")
        target = Artifact("target")
        network = make_network(
            Tool("Prepare", inputs=[start], outputs=[middle]),
            Tool("Finish", inputs=[middle], outputs=[target]),
        )

        plans = network.discover_continuation_plans(
            available_artifacts=["middle"],
            anchor_artifacts=["middle"],
            target_artifacts=["target"],
        )

        self.assertEqual(tool_sets(plans), {("Finish",)})
        self.assertEqual(plans[0].starting_artifacts, ["middle"])
        self.assertEqual(plans[0].target_artifacts, ["target"])

    def test_returns_minimal_alternative_routes_with_a_shared_first_tool(
        self,
    ):
        anchor = Artifact("anchor")
        prepared = Artifact("prepared")
        custom = Artifact("custom")
        target = Artifact("target")
        network = make_network(
            Tool("Prepare", inputs=[anchor], outputs=[prepared]),
            Tool("Quick", inputs=[prepared], outputs=[target]),
            Tool("Customize", inputs=[prepared], outputs=[custom]),
            Tool("Finish custom", inputs=[custom], outputs=[target]),
        )

        plans = network.discover_continuation_plans(
            available_artifacts=["anchor"],
            anchor_artifacts=["anchor"],
            target_artifacts=["target"],
        )

        self.assertEqual(
            [tuple(plan.tool_names) for plan in plans],
            [
                ("Prepare", "Quick"),
                ("Prepare", "Customize", "Finish custom"),
            ],
        )

    def test_available_join_input_does_not_require_its_network_producer(
        self,
    ):
        anchor = Artifact("anchor")
        left = Artifact("left")
        source = Artifact("source")
        right = Artifact("right")
        target = Artifact("target")
        network = make_network(
            Tool("Make left", inputs=[anchor], outputs=[left]),
            Tool("Make right", inputs=[source], outputs=[right]),
            Tool("Combine", inputs=[left, right], outputs=[target]),
        )

        plans = network.discover_continuation_plans(
            available_artifacts=["anchor", "right"],
            anchor_artifacts=["anchor"],
            target_artifacts=["target"],
        )

        self.assertEqual(
            tool_sets(plans),
            {("Make left", "Combine")},
        )

    def test_unavailable_join_input_requires_one_of_its_network_producers(
        self,
    ):
        anchor = Artifact("anchor")
        left = Artifact("left")
        source = Artifact("source")
        right = Artifact("right")
        target = Artifact("target")
        network = make_network(
            Tool("Make left", inputs=[anchor], outputs=[left]),
            Tool("Make right", inputs=[source], outputs=[right]),
            Tool("Combine", inputs=[left, right], outputs=[target]),
        )

        plans = network.discover_continuation_plans(
            available_artifacts=["anchor"],
            anchor_artifacts=["anchor"],
            target_artifacts=["target"],
        )

        self.assertEqual(
            tool_sets(plans),
            {("Make left", "Make right", "Combine")},
        )
        self.assertEqual(
            plans[0].missing_input_requirements({"anchor"}).initial_artifacts,
            {"source"},
        )

    def test_external_input_can_remain_a_missing_plan_requirement(self):
        anchor = Artifact("anchor")
        credential = Artifact("credential")
        target = Artifact("target")
        network = make_network(
            Tool(
                "Finish",
                inputs=[anchor, credential],
                outputs=[target],
            ),
        )

        plans = network.discover_continuation_plans(
            available_artifacts=["anchor"],
            anchor_artifacts=["anchor"],
            target_artifacts=["target"],
        )

        self.assertEqual(tool_sets(plans), {("Finish",)})
        self.assertEqual(
            plans[0].missing_input_requirements({"anchor"}).initial_artifacts,
            {"credential"},
        )

    def test_cycle_is_kept_as_one_structural_component(self):
        anchor = Artifact("anchor")
        draft = Artifact("draft")
        review = Artifact("review")
        target = Artifact("target")
        network = make_network(
            Tool("Enter", inputs=[anchor], outputs=[draft]),
            Tool("Review", inputs=[draft], outputs=[review]),
            Tool("Revise", inputs=[review], outputs=[draft]),
            Tool("Publish", inputs=[review], outputs=[target]),
        )

        plans = network.discover_continuation_plans(
            available_artifacts=["anchor"],
            anchor_artifacts=["anchor"],
            target_artifacts=["target"],
        )

        self.assertEqual(
            tool_sets(plans),
            {("Enter", "Review", "Revise", "Publish")},
        )

    def test_irrelevant_available_artifact_does_not_constrain_the_plan(self):
        anchor = Artifact("anchor")
        noise_input = Artifact("noise input")
        noise = Artifact("noise")
        target = Artifact("target")
        network = make_network(
            Tool("Finish", inputs=[anchor], outputs=[target]),
            Tool("Unrelated", inputs=[noise_input], outputs=[noise]),
        )

        plans = network.discover_continuation_plans(
            available_artifacts=["anchor", "noise"],
            anchor_artifacts=["anchor"],
            target_artifacts=["target"],
        )

        self.assertEqual(tool_sets(plans), {("Finish",)})

    def test_keeps_only_relevant_anchors_in_each_plan_boundary(self):
        useful = Artifact("useful")
        unused_input = Artifact("unused input")
        unused = Artifact("unused")
        target = Artifact("target")
        network = make_network(
            Tool("Finish", inputs=[useful], outputs=[target]),
            Tool("Unrelated", inputs=[unused_input], outputs=[unused]),
        )

        plans = network.discover_continuation_plans(
            available_artifacts=["useful", "unused"],
            anchor_artifacts=["useful", "unused"],
            target_artifacts=["target"],
        )

        self.assertEqual(tool_sets(plans), {("Finish",)})
        self.assertEqual(plans[0].starting_artifacts, ["useful"])

    def test_rejects_unknown_empty_and_unavailable_boundaries(self):
        anchor = Artifact("anchor")
        target = Artifact("target")
        network = make_network(
            Tool("Finish", inputs=[anchor], outputs=[target]),
        )

        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            network.discover_continuation_plans(
                available_artifacts=["anchor"],
                anchor_artifacts=[],
                target_artifacts=["target"],
            )

        with self.assertRaisesRegex(ValueError, "Unknown artifacts"):
            network.discover_continuation_plans(
                available_artifacts=["anchor"],
                anchor_artifacts=["anchor"],
                target_artifacts=["unknown"],
            )

        with self.assertRaisesRegex(ValueError, "already be available"):
            network.discover_continuation_plans(
                available_artifacts=[],
                anchor_artifacts=["anchor"],
                target_artifacts=["target"],
            )


if __name__ == "__main__":
    unittest.main()
