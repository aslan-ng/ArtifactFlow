import unittest

import numpy as np

from artifactflow.artifact.artifact import Artifact
from artifactflow.tool.tool import Tool
from artifactflow.workflow.workflow import Workflow


def make_workflow(*tools: Tool) -> Workflow:
    workflow = Workflow()
    for tool in tools:
        workflow.add_tool(tool)
    return workflow


class TestWorkflowCompatibilityScore(unittest.TestCase):
    def test_combines_artifacts_from_multiple_producer_tools(self):
        artifact_a = Artifact("a")
        artifact_b = Artifact("b")
        missing = Artifact("missing")
        producer_a = Tool("producer a", outputs=[artifact_a])
        producer_b = Tool("producer b", outputs=[artifact_b])
        consumer = Tool(
            "consumer",
            inputs=[artifact_a, artifact_b, missing],
        )
        workflow = make_workflow(producer_a, producer_b, consumer)

        self.assertEqual(
            workflow.tool_readiness_scores(),
            {"consumer": 2 / 3},
        )
        self.assertEqual(workflow.compatibility_score(), 2 / 3)

    def test_compatibility_score_averages_receiving_tools(self):
        artifact_a = Artifact("a")
        artifact_b = Artifact("b")
        missing = Artifact("missing")
        producer = Tool(
            "producer",
            outputs=[artifact_a, artifact_b],
        )
        partial_consumer = Tool(
            "partial consumer",
            inputs=[artifact_a, missing],
        )
        ready_consumer = Tool(
            "ready consumer",
            inputs=[artifact_b],
        )
        workflow = make_workflow(
            producer,
            partial_consumer,
            ready_consumer,
        )

        self.assertEqual(
            workflow.tool_readiness_scores(),
            {
                "partial consumer": 0.5,
                "ready consumer": 1.0,
            },
        )
        self.assertEqual(workflow.compatibility_score(), 0.75)

    def test_workflow_without_handoffs_is_vacuously_compatible(self):
        workflow = make_workflow(Tool("standalone"))

        self.assertEqual(workflow.tool_readiness_scores(), {})
        self.assertEqual(workflow.compatibility_score(), 1.0)

    def test_negative_missing_input_penalty_is_rejected(self):
        workflow = Workflow()

        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            workflow.compatibility_score(-1.0)


class TestWorkflowInputRequirements(unittest.TestCase):
    def setUp(self):
        self.artifact_a = Artifact("A")
        self.artifact_b = Artifact("B")
        self.tool_1 = Tool(
            "Tool 1",
            inputs=[self.artifact_a],
            outputs=[self.artifact_b],
        )
        self.tool_2 = Tool(
            "Tool 2",
            inputs=[self.artifact_b],
            outputs=[self.artifact_a],
        )
        self.cycle = make_workflow(self.tool_1, self.tool_2)

    def test_starting_tool_selects_the_bootstrap_artifact(self):
        requirements = self.cycle.input_requirements(["Tool 1"])

        self.assertEqual(requirements.external_artifacts, set())
        self.assertEqual(requirements.bootstrap_artifacts, {"A"})
        self.assertEqual(requirements.initial_artifacts, {"A"})
        self.assertEqual(requirements.blocked_tools, set())
        self.assertEqual(
            requirements.unreplenished_bootstrap_artifacts,
            set(),
        )
        self.assertTrue(requirements.is_runnable)

        reverse_requirements = self.cycle.input_requirements(["Tool 2"])

        self.assertEqual(
            reverse_requirements.bootstrap_artifacts,
            {"B"},
        )

    def test_producerless_inputs_are_always_external(self):
        external = Artifact("external")
        internal = Artifact("internal")
        result = Artifact("result")
        first = Tool(
            "first",
            inputs=[external],
            outputs=[internal],
        )
        second = Tool(
            "second",
            inputs=[internal],
            outputs=[result],
        )
        workflow = make_workflow(first, second)

        requirements = workflow.input_requirements(["first"])

        self.assertEqual(requirements.external_artifacts, {"external"})
        self.assertEqual(requirements.bootstrap_artifacts, set())
        self.assertEqual(requirements.initial_artifacts, {"external"})
        self.assertTrue(requirements.is_runnable)

    def test_reports_when_bootstrap_does_not_unlock_the_workflow(self):
        artifact_x = Artifact("X")
        artifact_c = Artifact("C")
        starter = Tool(
            "starter",
            inputs=[self.artifact_a],
            outputs=[artifact_x],
        )
        producer_a = Tool(
            "producer A",
            inputs=[self.artifact_b],
            outputs=[self.artifact_a, artifact_c],
        )
        producer_b = Tool(
            "producer B",
            inputs=[artifact_c],
            outputs=[self.artifact_b],
        )
        workflow = make_workflow(starter, producer_a, producer_b)

        requirements = workflow.input_requirements(["starter"])

        self.assertEqual(requirements.bootstrap_artifacts, {"A"})
        self.assertEqual(
            requirements.blocked_tools,
            {"producer A", "producer B"},
        )
        self.assertEqual(
            requirements.unreplenished_bootstrap_artifacts,
            {"A"},
        )
        self.assertFalse(requirements.is_runnable)

    def test_requires_known_starting_tools(self):
        with self.assertRaisesRegex(ValueError, "At least one"):
            self.cycle.input_requirements([])

        with self.assertRaisesRegex(ValueError, "Unknown starting tools"):
            self.cycle.input_requirements(["missing"])


class TestWorkflowSimilarityScore(unittest.TestCase):
    def setUp(self):
        artifact_x = Artifact("x")
        artifact_y = Artifact("y")
        artifact_z = Artifact("z")
        first = Tool(
            "first",
            inputs=[artifact_x],
            outputs=[artifact_y],
        )
        second = Tool(
            "second",
            inputs=[artifact_y],
            outputs=[artifact_z],
        )
        self.short_workflow = make_workflow(first)
        self.long_workflow = make_workflow(first, second)

    def test_identical_workflows_have_similarity_one(self):
        same_workflow = make_workflow(*self.short_workflow.tools)

        self.assertAlmostEqual(
            self.short_workflow.similarity_score(same_workflow),
            1.0,
        )

    def test_uses_union_alignment_for_different_workflows(self):
        score = self.short_workflow.similarity_score(self.long_workflow)

        self.assertAlmostEqual(score, 2 / 3)
        self.assertAlmostEqual(
            score,
            self.long_workflow.similarity_score(self.short_workflow),
        )
        self.assertTrue(np.isfinite(score))


if __name__ == "__main__":
    unittest.main()
