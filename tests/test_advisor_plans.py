import unittest

from artifactflow import Advisor, Artifact, Project, Tool, Workflow


def make_join_workflow() -> Workflow:
    left_seed = Artifact("Left seed")
    right_seed = Artifact("Right seed")
    left = Artifact("Left")
    right = Artifact("Right")
    result = Artifact("Result")

    workflow = Workflow()
    for tool in (
        Tool("Make left", inputs=[left_seed], outputs=[left]),
        Tool("Make right", inputs=[right_seed], outputs=[right]),
        Tool("Join", inputs=[left, right], outputs=[result]),
    ):
        workflow.add_tool(tool)
    workflow.starting_artifacts = ["Left seed", "Right seed"]
    workflow.target_artifacts = ["Result"]
    return workflow


class TestPlanFrontier(unittest.TestCase):
    def test_runs_both_independent_prerequisites_before_a_join(self):
        project = Project(make_join_workflow())
        advisor = Advisor(project)

        command = advisor.advise()
        self.assertEqual(
            tuple(option.tool_name for option in command.options),
            ("Make left", "Make right"),
        )

        project.record_tool_success("Make left")
        command = advisor.advise()
        self.assertEqual(
            tuple(option.tool_name for option in command.options),
            ("Make right",),
        )
        self.assertEqual(
            command.options[0].missing_artifacts,
            ("Right seed",),
        )

        project.record_tool_success("Make right")
        command = advisor.advise()
        self.assertEqual(
            tuple(option.tool_name for option in command.options),
            ("Join",),
        )
        self.assertEqual(command.options[0].missing_artifacts, ())

        project.record_tool_success("Join")
        self.assertEqual(advisor.advise().status, "COMPLETE")

    def test_an_exhausted_required_prerequisite_is_not_retried_as_a_route(self):
        project = Project(make_join_workflow())
        advisor = Advisor(project)
        project.record_tool_success("Make left")

        project.record_tool_failure("Make right", "failed")
        self.assertEqual(advisor.advise().options[0].action, "RETRY")
        project.record_tool_failure("Make right", "failed again")

        command = advisor.advise()
        self.assertEqual(command.status, "BLOCKED")
        self.assertEqual(command.options, ())

    def test_an_exhausted_join_does_not_reopen_completed_prerequisites(self):
        project = Project(make_join_workflow())
        advisor = Advisor(project)
        project.record_tool_success("Make left")
        project.record_tool_success("Make right")

        project.record_tool_failure("Join", "failed")
        self.assertEqual(advisor.advise().options[0].action, "RETRY")
        project.record_tool_failure("Join", "failed again")

        command = advisor.advise()
        self.assertEqual(command.status, "BLOCKED")
        self.assertEqual(command.options, ())

    def test_tools_outside_every_target_reaching_plan_are_not_options(self):
        start = Artifact("Start")
        prepared = Artifact("Prepared")
        dead = Artifact("Dead")
        result = Artifact("Result")
        workflow = Workflow()
        for tool in (
            Tool("Prepare", inputs=[start], outputs=[prepared]),
            Tool("Finish", inputs=[prepared], outputs=[result]),
            Tool("Dead end", inputs=[prepared], outputs=[dead]),
        ):
            workflow.add_tool(tool)
        workflow.starting_artifacts = ["Start"]
        workflow.target_artifacts = ["Result"]

        project = Project(workflow)
        advisor = Advisor(project)
        project.record_tool_success("Prepare")

        self.assertEqual(
            tuple(option.tool_name for option in advisor.advise().options),
            ("Finish",),
        )

    def test_observed_work_after_completion_does_not_reopen_the_project(self):
        start = Artifact("Start")
        result = Artifact("Result")
        side_output = Artifact("Side output")
        workflow = Workflow()
        workflow.add_tool(
            Tool("Finish", inputs=[start], outputs=[result])
        )
        workflow.starting_artifacts = ["Start"]
        workflow.target_artifacts = ["Result"]
        network = workflow.to_tool_network()
        network.add_tool(
            Tool("Late side task", inputs=[start], outputs=[side_output])
        )
        project = Project(workflow, tool_network=network)
        advisor = Advisor(project)
        advisor.advise()
        project.record_tool_success("Finish")
        project.record_tool_success("Late side task")

        command = advisor.advise()

        self.assertEqual(command.status, "COMPLETE")
        self.assertIsNotNone(command.deviation)
        assert command.deviation is not None
        self.assertEqual(command.deviation.observed_tool, "Late side task")
        self.assertEqual(command.deviation.location, "TOOL_NETWORK")


class TestMultiTargetAcceptance(unittest.TestCase):
    def test_cycle_regenerates_only_its_target_and_retains_static_target(self):
        start = Artifact("Start")
        x = Artifact("X")
        draft = Artifact("Draft")
        renewable_a = Artifact("A")
        static_b = Artifact("B")
        workflow = Workflow()
        for tool in (
            Tool(
                "Initialize",
                inputs=[start],
                outputs=[x, static_b],
            ),
            Tool("Write", inputs=[x], outputs=[draft]),
            Tool(
                "Evaluate",
                inputs=[draft],
                outputs=[x, renewable_a],
            ),
        ):
            workflow.add_tool(tool)
        workflow.starting_artifacts = ["Start"]
        workflow.target_artifacts = ["A", "B"]
        project = Project(workflow)
        advisor = Advisor(project)

        initialized = project.record_tool_success("Initialize")
        b_v1 = next(
            artifact
            for artifact in initialized.outputs
            if artifact.artifact_name == "B"
        )
        project.record_tool_success("Write")
        first_evaluation = project.record_tool_success("Evaluate")
        a_v1 = next(
            artifact
            for artifact in first_evaluation.outputs
            if artifact.artifact_name == "A"
        )

        first_candidate = advisor.advise()

        self.assertEqual(first_candidate.status, "COMMAND")
        self.assertTrue(first_candidate.target_acceptance_required)
        self.assertEqual(first_candidate.target_artifacts, ("A", "B"))
        self.assertEqual(
            first_candidate.options[0].tool_name,
            "Write",
        )
        first_state = advisor._replay_log().active
        self.assertIs(first_state.target_candidates["A"], a_v1)
        self.assertIs(first_state.target_candidates["B"], b_v1)

        project.record_tool_success("Write")
        between_candidates = advisor.advise()
        between_state = advisor._replay_log().active

        self.assertEqual(between_candidates.target_artifacts, ())
        self.assertNotIn("A", between_state.target_candidates)
        self.assertIs(between_state.target_candidates["B"], b_v1)

        second_evaluation = project.record_tool_success("Evaluate")
        a_v2 = next(
            artifact
            for artifact in second_evaluation.outputs
            if artifact.artifact_name == "A"
        )
        second_candidate = advisor.advise()

        self.assertEqual(a_v2.version, 2)
        self.assertEqual(b_v1.version, 1)
        self.assertTrue(second_candidate.target_acceptance_required)
        self.assertEqual(second_candidate.target_artifacts, ("A", "B"))
        second_state = advisor._replay_log().active
        self.assertIs(second_state.target_candidates["A"], a_v2)
        self.assertIs(second_state.target_candidates["B"], b_v1)

        project.record_target_acceptance((a_v2, b_v1))
        self.assertEqual(advisor.advise().status, "COMPLETE")


if __name__ == "__main__":
    unittest.main()
