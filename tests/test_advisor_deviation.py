import unittest

from artifactflow import Artifact, Project, Tool, Workflow
from artifactflow.advisor import (
    Advisor,
    BALANCED,
    HOMOPHILIC,
    NORMATIVE,
)


def make_branching_workflow() -> Workflow:
    """Return two plans with one shared prefix and distinct finishes."""
    start = Artifact("Start")
    prepared = Artifact("Prepared")
    route_a = Artifact("Route A")
    route_b = Artifact("Route B")
    result = Artifact("Result")

    workflow = Workflow()
    for tool in (
        Tool("Prepare", inputs=[start], outputs=[prepared]),
        Tool("Choose A", inputs=[prepared], outputs=[route_a]),
        Tool("Finish A", inputs=[route_a], outputs=[result]),
        Tool("Choose B", inputs=[prepared], outputs=[route_b]),
        Tool("Finish B", inputs=[route_b], outputs=[result]),
    ):
        workflow.add_tool(tool)
    workflow.starting_artifacts = ["Start"]
    workflow.target_artifacts = ["Result"]
    return workflow


def make_network_deviation_project() -> Project:
    """Return a linear workflow inside a network with one extra route."""
    start = Artifact("Start")
    prepared = Artifact("Prepared")
    preferred = Artifact("Preferred draft")
    improvised = Artifact("Improvised draft")
    result = Artifact("Result")

    workflow = Workflow()
    for tool in (
        Tool("Prepare", inputs=[start], outputs=[prepared]),
        Tool(
            "Preferred step",
            inputs=[prepared],
            outputs=[preferred],
        ),
        Tool(
            "Preferred finish",
            inputs=[preferred],
            outputs=[result],
        ),
    ):
        workflow.add_tool(tool)
    workflow.starting_artifacts = ["Start"]
    workflow.target_artifacts = ["Result"]

    network = workflow.to_tool_network()
    network.add_tool(
        Tool(
            "Improvised step",
            inputs=[prepared],
            outputs=[improvised],
        )
    )
    network.add_tool(
        Tool(
            "Improvised finish",
            inputs=[improvised],
            outputs=[result],
        )
    )
    return Project(workflow, tool_network=network)


def make_dead_workflow_continuation_project() -> Project:
    """Return a network deviation with one useless Workflow consumer."""
    start = Artifact("Start")
    prepared = Artifact("Prepared")
    preferred = Artifact("Preferred draft")
    improvised = Artifact("Improvised draft")
    dead_end = Artifact("Dead end")
    result = Artifact("Result")

    workflow = Workflow()
    for tool in (
        Tool("Prepare", inputs=[start], outputs=[prepared]),
        Tool(
            "Preferred step",
            inputs=[prepared],
            outputs=[preferred],
        ),
        Tool(
            "Preferred finish",
            inputs=[preferred],
            outputs=[result],
        ),
        Tool(
            "Dead inspection",
            inputs=[improvised],
            outputs=[dead_end],
        ),
    ):
        workflow.add_tool(tool)
    workflow.starting_artifacts = ["Start"]
    workflow.target_artifacts = ["Result"]

    network = workflow.to_tool_network()
    network.add_tool(
        Tool(
            "Improvised step",
            inputs=[prepared],
            outputs=[improvised],
        )
    )
    network.add_tool(
        Tool(
            "Improvised finish",
            inputs=[improvised],
            outputs=[result],
        )
    )
    return Project(workflow, tool_network=network)


def root_names(command) -> tuple[str, ...]:
    return tuple(option.tool_name for option in command.options)


class TestAdvisorHistoryAndNarrowing(unittest.TestCase):
    def test_shared_next_tool_is_shown_once_with_both_supporting_plans(self):
        project = Project(make_branching_workflow())
        advisor = Advisor(project)

        command = advisor.advise()

        self.assertEqual(root_names(command), ("Prepare",))
        snapshot = advisor.advice_history.latest()
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.visible_root_tools, ("Prepare",))
        self.assertEqual(
            set(snapshot.plans_for("Prepare")),
            {
                ("Prepare", "Choose A", "Finish A"),
                ("Prepare", "Choose B", "Finish B"),
            },
        )

    def test_a_unique_branch_narrows_the_active_plan_and_parks_its_sibling(self):
        project = Project(make_branching_workflow())
        advisor = Advisor(project)

        advisor.advise()
        project.record_tool_success("Prepare")
        branch_command = advisor.advise()
        self.assertEqual(
            root_names(branch_command),
            ("Choose A", "Choose B"),
        )

        project.record_tool_success("Choose A")
        narrowed = advisor.advise()

        self.assertEqual(root_names(narrowed), ("Finish A",))
        snapshot = advisor.advice_history.latest()
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(
            snapshot.plans_for("Finish A"),
            (("Prepare", "Choose A", "Finish A"),),
        )
        self.assertNotIn("Choose B", snapshot.visible_root_tools)


class TestAdvisorFailureAndDeviation(unittest.TestCase):
    def test_failure_is_a_command_with_a_retry_action(self):
        project = Project(make_branching_workflow())
        advisor = Advisor(project)

        advisor.advise()
        project.record_tool_failure("Prepare", "temporary timeout")
        command = advisor.advise()

        self.assertEqual(command.status, "COMMAND")
        self.assertFalse(hasattr(command, "recovery"))
        self.assertEqual(command.options[0].action, "RETRY")

    def test_an_unshown_workflow_plan_is_accepted_and_reported(self):
        project = Project(make_branching_workflow())
        advisor = Advisor(
            project,
            max_options=1,
            character=HOMOPHILIC,
        )

        advisor.advise()
        project.record_tool_success("Prepare")
        proposed = advisor.advise()
        self.assertEqual(root_names(proposed), ("Choose A",))

        project.record_tool_success("Choose B")
        command = advisor.advise()

        self.assertEqual(command.status, "COMMAND")
        self.assertEqual(root_names(command), ("Finish B",))
        self.assertIsNotNone(command.deviation)
        assert command.deviation is not None
        self.assertEqual(command.deviation.observed_tool, "Choose B")
        self.assertEqual(command.deviation.location, "WORKFLOW")
        self.assertEqual(command.deviation.proposed_options, ("Choose A",))

    def test_character_changes_order_after_a_tool_network_deviation(self):
        def advice_for(character):
            project = make_network_deviation_project()
            advisor = Advisor(project, character=character)
            advisor.advise()
            project.record_tool_success("Prepare")
            proposed = advisor.advise()
            self.assertEqual(root_names(proposed), ("Preferred step",))
            project.record_tool_success("Improvised step")
            return advisor, advisor.advise()

        _, normative = advice_for(NORMATIVE)
        _, homophilic = advice_for(HOMOPHILIC)
        balanced_advisor, balanced = advice_for(BALANCED)

        self.assertEqual(
            root_names(normative),
            ("Preferred step", "Improvised finish"),
        )
        self.assertEqual(
            root_names(homophilic),
            ("Improvised finish", "Preferred step"),
        )
        self.assertEqual(
            set(root_names(balanced)),
            {"Preferred step", "Improvised finish"},
        )
        self.assertEqual(
            root_names(balanced_advisor.advise()),
            root_names(balanced),
        )

        by_name = {
            option.tool_name: option
            for option in normative.options
        }
        self.assertEqual(
            by_name["Preferred step"].scope,
            "PROPOSED_PLAN",
        )
        self.assertEqual(
            by_name["Preferred step"].transition,
            "RESTORE_CHECKPOINT",
        )
        self.assertEqual(
            by_name["Improvised finish"].scope,
            "TOOL_NETWORK",
        )
        self.assertEqual(
            by_name["Improvised finish"].transition,
            "CONTINUE_CURRENT",
        )

    def test_normative_restore_completes_without_erasing_deviation_facts(
        self,
    ):
        project = make_network_deviation_project()
        advisor = Advisor(project, character=NORMATIVE)
        advisor.advise()
        project.record_tool_success("Prepare")
        advisor.advise()

        deviating_event = project.record_tool_success("Improvised step")
        command = advisor.advise()
        restore = command.options[0]

        self.assertEqual(restore.tool_name, "Preferred step")
        self.assertEqual(restore.transition, "RESTORE_CHECKPOINT")
        project.record_tool_success(restore.tool_name)
        self.assertEqual(
            root_names(advisor.advise()),
            ("Preferred finish",),
        )
        project.record_tool_success("Preferred finish")

        self.assertEqual(advisor.advise().status, "COMPLETE")
        self.assertIs(
            project.latest_artifact("Improvised draft"),
            deviating_event.outputs[0],
        )
        self.assertIn("Improvised draft", project.available_artifacts)
        replay = advisor._replay_log()
        self.assertNotIn(
            "Improvised draft",
            replay.active.active_artifacts,
        )

    def test_homophilic_continuation_completes_through_the_network(self):
        project = make_network_deviation_project()
        advisor = Advisor(project, character=HOMOPHILIC)
        advisor.advise()
        project.record_tool_success("Prepare")
        advisor.advise()
        project.record_tool_success("Improvised step")

        command = advisor.advise()
        continuation = command.options[0]
        self.assertEqual(continuation.tool_name, "Improvised finish")
        self.assertEqual(continuation.transition, "CONTINUE_CURRENT")

        project.record_tool_success(continuation.tool_name)
        completed = advisor.advise()

        self.assertEqual(completed.status, "COMPLETE")
        self.assertEqual(completed.target_artifacts, ("Result",))
        self.assertIn(
            "Improvised draft",
            advisor._replay_log().active.active_artifacts,
        )

    def test_failed_network_deviation_retries_once_then_restores_workflow(
        self,
    ):
        project = make_network_deviation_project()
        advisor = Advisor(project, character=NORMATIVE)
        advisor.advise()
        project.record_tool_success("Prepare")
        advisor.advise()

        project.record_tool_failure("Improvised step", "first failure")
        retry = advisor.advise()

        self.assertEqual(retry.status, "COMMAND")
        self.assertEqual(retry.options[0].tool_name, "Improvised step")
        self.assertEqual(retry.options[0].action, "RETRY")

        project.record_tool_failure("Improvised step", "retry failure")
        fallback = advisor.advise()

        self.assertEqual(fallback.status, "COMMAND")
        self.assertEqual(fallback.options[0].tool_name, "Preferred step")
        self.assertNotIn("Improvised step", root_names(fallback))

        project.record_tool_success("Preferred step")
        self.assertEqual(
            root_names(advisor.advise()),
            ("Preferred finish",),
        )
        project.record_tool_success("Preferred finish")
        self.assertEqual(advisor.advise().status, "COMPLETE")


class TestAdvisorDeviationRegressions(unittest.TestCase):
    def test_out_of_order_plan_tool_keeps_its_output_and_continues(self):
        start = Artifact("Start")
        prepared = Artifact("Prepared")
        transformed = Artifact("Transformed")
        result = Artifact("Result")
        workflow = Workflow()
        for tool in (
            Tool("Prepare", inputs=[start], outputs=[prepared]),
            Tool(
                "Transform",
                inputs=[prepared],
                outputs=[transformed],
            ),
            Tool("Finish", inputs=[transformed], outputs=[result]),
        ):
            workflow.add_tool(tool)
        workflow.starting_artifacts = ["Start"]
        workflow.target_artifacts = ["Result"]
        project = Project(workflow)
        advisor = Advisor(project, character=HOMOPHILIC)

        self.assertEqual(root_names(advisor.advise()), ("Prepare",))
        out_of_order = project.record_tool_success("Transform")
        command = advisor.advise()

        self.assertIsNotNone(command.deviation)
        self.assertEqual(command.options[0].tool_name, "Finish")
        self.assertEqual(
            command.options[0].transition,
            "CONTINUE_CURRENT",
        )
        self.assertIs(
            advisor._replay_log().active.active_artifacts["Transformed"],
            out_of_order.outputs[0],
        )

        project.record_tool_success("Finish")
        self.assertEqual(advisor.advise().status, "COMPLETE")

    def test_dead_workflow_consumer_is_excluded_after_deviation(self):
        project = make_dead_workflow_continuation_project()
        advisor = Advisor(project, character=HOMOPHILIC)
        advisor.advise()
        project.record_tool_success("Prepare")
        advisor.advise()
        project.record_tool_success("Improvised step")

        command = advisor.advise()

        self.assertIn("Improvised finish", root_names(command))
        self.assertNotIn("Dead inspection", root_names(command))

    def test_colliding_tool_and_artifact_names_do_not_skip_producer(self):
        start = Artifact("Start")
        colliding_artifact = Artifact("Consume")
        result = Artifact("Result")
        workflow = Workflow()
        workflow.add_tool(
            Tool(
                "Produce",
                inputs=[start],
                outputs=[colliding_artifact],
            )
        )
        workflow.add_tool(
            Tool(
                "Consume",
                inputs=[colliding_artifact],
                outputs=[result],
            )
        )
        workflow.starting_artifacts = ["Start"]
        workflow.target_artifacts = ["Result"]
        project = Project(workflow)
        advisor = Advisor(project)

        self.assertEqual(root_names(advisor.advise()), ("Produce",))
        project.record_tool_success("Produce")
        self.assertEqual(root_names(advisor.advise()), ("Consume",))

    def test_same_tool_keeps_current_and_restored_input_bindings(self):
        start = Artifact("Start")
        x = Artifact("X")
        result = Artifact("Result")
        workflow = Workflow()
        workflow.add_tool(Tool("Prepare", inputs=[start], outputs=[x]))
        workflow.add_tool(Tool("Use X", inputs=[x], outputs=[result]))
        workflow.starting_artifacts = ["Start"]
        workflow.target_artifacts = ["Result"]
        network = workflow.to_tool_network()
        network.add_tool(Tool("Revise X", inputs=[x], outputs=[x]))
        project = Project(workflow, tool_network=network)
        advisor = Advisor(project, character=HOMOPHILIC)

        advisor.advise()
        prepared = project.record_tool_success("Prepare")
        x_v1 = prepared.outputs[0]
        advisor.advise()
        revised = project.record_tool_success("Revise X")
        x_v2 = revised.outputs[0]

        command = advisor.advise()
        use_x_options = tuple(
            option
            for option in command.options
            if option.tool_name == "Use X"
        )

        self.assertEqual(len(use_x_options), 2)
        self.assertEqual(
            {option.input_artifacts for option in use_x_options},
            {
                (("X", x_v1.version),),
                (("X", x_v2.version),),
            },
        )
        by_transition = {
            option.transition: option
            for option in use_x_options
        }
        self.assertEqual(
            by_transition["CONTINUE_CURRENT"].input_artifacts,
            (("X", x_v2.version),),
        )
        self.assertEqual(
            by_transition["RESTORE_CHECKPOINT"].input_artifacts,
            (("X", x_v1.version),),
        )

        project.record_tool_success("Use X", inputs=(x_v1,))
        self.assertEqual(advisor.advise().status, "COMPLETE")
        replay = advisor._replay_log()
        self.assertIs(replay.active.active_artifacts["X"], x_v1)
        self.assertIs(project.latest_artifact("X"), x_v2)

    def test_unadvised_failure_retries_the_exact_older_input_version(self):
        start = Artifact("Start")
        x = Artifact("X")
        result = Artifact("Result")
        workflow = Workflow()
        workflow.add_tool(Tool("Prepare", inputs=[start], outputs=[x]))
        workflow.add_tool(Tool("Use X", inputs=[x], outputs=[result]))
        workflow.starting_artifacts = ["Start"]
        workflow.target_artifacts = ["Result"]
        network = workflow.to_tool_network()
        network.add_tool(Tool("Revise X", inputs=[x], outputs=[x]))
        network.add_tool(Tool("Probe X", inputs=[x], outputs=[result]))
        project = Project(workflow, tool_network=network)
        advisor = Advisor(
            project,
            character=NORMATIVE,
            max_options=1,
        )

        advisor.advise()
        prepared = project.record_tool_success("Prepare")
        x_v1 = prepared.outputs[0]
        advisor.advise()
        revised = project.record_tool_success("Revise X")
        x_v2 = revised.outputs[0]
        self.assertNotIn("Probe X", root_names(advisor.advise()))

        project.record_tool_failure(
            "Probe X",
            "temporary failure",
            inputs=(x_v1,),
        )
        retry = advisor.advise()

        self.assertEqual(retry.status, "COMMAND")
        self.assertEqual(retry.options[0].tool_name, "Probe X")
        self.assertEqual(retry.options[0].action, "RETRY")
        self.assertEqual(
            retry.options[0].input_artifacts,
            (("X", x_v1.version),),
        )
        self.assertIs(project.latest_artifact("X"), x_v2)

        project.record_tool_success("Probe X", inputs=(x_v1,))
        self.assertEqual(advisor.advise().status, "COMPLETE")
        self.assertIs(
            advisor._replay_log().active.active_artifacts["X"],
            x_v1,
        )
        self.assertIs(project.latest_artifact("X"), x_v2)

    def test_hidden_exact_restore_uses_its_checkpoint_and_drops_newer_q(
        self,
    ):
        start = Artifact("Start")
        x = Artifact("X")
        q = Artifact("Q")
        draft = Artifact("Draft")
        result = Artifact("Result")
        workflow = Workflow()
        workflow.add_tool(Tool("Prepare", inputs=[start], outputs=[x]))
        workflow.add_tool(Tool("Use X", inputs=[x], outputs=[draft]))
        workflow.add_tool(
            Tool(
                "Finish",
                inputs=[draft, q],
                outputs=[result],
            )
        )
        workflow.starting_artifacts = ["Start"]
        workflow.target_artifacts = ["Result"]
        network = workflow.to_tool_network()
        network.add_tool(Tool("Revise", inputs=[x], outputs=[x, q]))
        project = Project(workflow, tool_network=network)
        advisor = Advisor(
            project,
            character=BALANCED,
            max_options=1,
        )

        advisor.advise()
        prepared = project.record_tool_success("Prepare")
        x_v1 = prepared.outputs[0]
        advisor.advise()
        revised = project.record_tool_success("Revise")
        x_v2, q_v1 = revised.outputs

        visible = advisor.advise()
        self.assertEqual(len(visible.options), 1)
        self.assertEqual(visible.options[0].tool_name, "Use X")
        self.assertEqual(
            visible.options[0].input_artifacts,
            (("X", x_v2.version),),
        )

        project.record_tool_success("Use X", inputs=(x_v1,))
        command = advisor.advise()

        self.assertEqual(root_names(command), ("Finish",))
        self.assertEqual(command.options[0].missing_artifacts, ("Q",))
        replay = advisor._replay_log()
        self.assertIs(replay.active.active_artifacts["X"], x_v1)
        self.assertNotIn("Q", replay.active.active_artifacts)
        self.assertIs(project.latest_artifact("X"), x_v2)
        self.assertIs(project.latest_artifact("Q"), q_v1)


if __name__ == "__main__":
    unittest.main()
