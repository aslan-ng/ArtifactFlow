import unittest

from artifactflow.advisor import Advisor
from artifactflow.artifact.artifact import Artifact
from artifactflow.project import Project
from artifactflow.project.log import (
    ArtifactAvailable,
    Log,
    TargetsAccepted,
    ToolFailed,
    ToolSucceeded,
)
from artifactflow.tool.tool import Tool
from artifactflow.user import User
from artifactflow.workflow.workflow import Workflow


def make_workflow(
    *tools: Tool,
    starting: list[str],
    target: list[str],
) -> Workflow:
    workflow = Workflow()
    for tool in tools:
        workflow.add_tool(tool)
    workflow.starting_artifacts = starting
    workflow.target_artifacts = target
    return workflow


class TestLog(unittest.TestCase):
    def test_records_events_in_order(self):
        log = Log()

        log.artifact_available("A")
        log.tool_succeeded("first")
        log.tool_failed("second", "simulated failure")
        log.targets_accepted()

        self.assertEqual(
            log.events,
            (
                ArtifactAvailable("A"),
                ToolSucceeded("first"),
                ToolFailed("second", "simulated failure"),
                TargetsAccepted(),
            ),
        )


class TestProjectAndUser(unittest.TestCase):
    def setUp(self):
        a = Artifact("A")
        b = Artifact("B")
        self.workflow = make_workflow(
            Tool("first", inputs=[a], outputs=[b]),
            starting=["A"],
            target=["B"],
        )

    def test_project_starts_with_an_empty_history(self):
        project = Project(self.workflow)

        self.assertEqual(project.events, ())
        self.assertEqual(project.available_artifacts, frozenset())

    def test_project_records_tool_facts(self):
        project = Project(self.workflow)

        project.record_tool_success("first")

        self.assertEqual(project.state.successful_tools, ("first",))
        self.assertEqual(project.available_artifacts, {"A", "B"})
        self.assertEqual(project.state.produced_artifacts, {"B"})

    def test_project_records_failed_attempts(self):
        project = Project(self.workflow)

        project.record_tool_failure("first", "simulated failure")

        self.assertEqual(project.state.failed_attempts, ("first",))
        self.assertEqual(
            project.events,
            (ToolFailed("first", "simulated failure"),),
        )

    def test_user_records_external_contributions(self):
        project = Project(self.workflow)
        user = User(project)

        user.provide("A")
        project.record_tool_success("first")
        user.accept_targets()

        self.assertEqual(
            project.events,
            (
                ArtifactAvailable("A"),
                ToolSucceeded("first"),
                TargetsAccepted(),
            ),
        )


class TestAdvisor(unittest.TestCase):
    def setUp(self):
        a = Artifact("A")
        b = Artifact("B")
        c = Artifact("C")
        d = Artifact("D")
        result = Artifact("result")
        self.workflow = make_workflow(
            Tool("first", inputs=[a], outputs=[b]),
            Tool("second", inputs=[b, c], outputs=[d]),
            Tool("third", inputs=[d], outputs=[a, c, result]),
            starting=["A"],
            target=["result"],
        )

    def test_finds_mandatory_bootstrap_artifacts(self):
        advisor = Advisor(Project(self.workflow))

        self.assertEqual(advisor.bootstrap_artifacts, ("A", "C"))
        self.assertEqual(
            advisor.mandatory_bootstrap_artifacts,
            ("A", "C"),
        )
        self.assertEqual(advisor.conditional_bootstrap_artifacts, ())

    def test_a_boundary_input_does_not_make_a_downstream_tool_start(self):
        project = Project(
            self.workflow,
            starting_artifacts=["A", "C"],
        )
        advisor = Advisor(project)

        self.assertEqual(advisor.bootstrap_artifacts, ("A", "C"))
        self.assertEqual(
            [option.tool_name for option in advisor.advise().options],
            ["first"],
        )

    def test_lookahead_attaches_missing_artifacts_to_their_consumers(self):
        advisor = Advisor(Project(self.workflow), lookahead_depth=2)

        command = advisor.advise()

        self.assertEqual(command.status, "COMMAND")
        self.assertEqual(
            [option.tool_name for option in command.options],
            ["first"],
        )
        self.assertEqual(
            command.options[0].missing_artifacts,
            ("A",),
        )
        second = command.options[0].continuations[0]
        self.assertEqual(second.tool_name, "second")
        self.assertEqual(second.missing_artifacts, ("C",))

    def test_successful_tools_advance_the_advisor(self):
        project = Project(self.workflow)
        advisor = Advisor(project)

        project.record_tool_success("first")
        command = advisor.advise()

        self.assertEqual(command.options[0].tool_name, "second")
        self.assertEqual(
            command.options[0].missing_artifacts,
            ("C",),
        )

        project.record_tool_success("second")
        project.record_tool_success("third")
        command = advisor.advise()

        self.assertEqual(command.status, "COMMAND")
        self.assertEqual(command.target_artifacts, ("result",))
        self.assertTrue(command.target_acceptance_required)

        User(project).accept_targets()
        command = advisor.advise()

        self.assertEqual(command.status, "COMPLETE")
        self.assertEqual(command.target_artifacts, ("result",))
        self.assertIn("result", project.available_artifacts)

    def test_an_early_artifact_removes_the_future_requirement(self):
        project = Project(self.workflow)
        advisor = Advisor(project, lookahead_depth=2)
        user = User(project)

        user.provide("C")
        command = advisor.advise()
        self.assertEqual(
            command.options[0].continuations[0].missing_artifacts,
            (),
        )

        project.record_tool_success("first")
        command = advisor.advise()
        self.assertEqual(command.options[0].missing_artifacts, ())

    def test_external_target_does_not_complete_the_project(self):
        project = Project(self.workflow)
        advisor = Advisor(project)

        User(project).provide("result")

        self.assertEqual(advisor.advise().status, "COMMAND")

    def test_rejects_a_tool_that_was_not_an_option(self):
        project = Project(self.workflow)
        advisor = Advisor(project)
        project.record_tool_success("second")

        with self.assertRaisesRegex(ValueError, "not an advised option"):
            advisor.advise()


class TestAlternativeRoutes(unittest.TestCase):
    def setUp(self):
        start = Artifact("start")
        fork = Artifact("fork")
        left_seed = Artifact("left seed")
        target = Artifact("target")
        self.workflow = make_workflow(
            Tool("start", inputs=[start], outputs=[fork]),
            Tool("left", inputs=[fork, left_seed], outputs=[target]),
            Tool("right", inputs=[fork], outputs=[target]),
            starting=["start"],
            target=["target"],
        )

    def test_separates_mandatory_and_conditional_bootstrap(self):
        advisor = Advisor(Project(self.workflow))

        self.assertEqual(advisor.bootstrap_artifacts, ("start", "left seed"))
        self.assertEqual(
            advisor.mandatory_bootstrap_artifacts,
            ("start",),
        )
        self.assertEqual(
            advisor.conditional_bootstrap_artifacts,
            ("left seed",),
        )

    def test_returns_route_options_with_local_requirements(self):
        project = Project(self.workflow)
        advisor = Advisor(project)
        project.record_tool_success("start")

        command = advisor.advise()

        self.assertEqual(
            [option.tool_name for option in command.options],
            ["left", "right"],
        )
        self.assertEqual(
            command.options[0].missing_artifacts,
            ("left seed",),
        )
        self.assertEqual(command.options[1].missing_artifacts, ())


class TestBootstrapLookaheadAfterRouteChoice(unittest.TestCase):
    def test_conditional_bootstrap_appears_on_its_future_consumer(self):
        start = Artifact("start")
        fork = Artifact("fork")
        left_output = Artifact("left output")
        middle_output = Artifact("middle output")
        late_seed = Artifact("late seed")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("start", inputs=[start], outputs=[fork]),
            Tool("choose left", inputs=[fork], outputs=[left_output]),
            Tool("choose right", inputs=[fork], outputs=[target]),
            Tool("middle", inputs=[left_output], outputs=[middle_output]),
            Tool(
                "finish left",
                inputs=[middle_output, late_seed],
                outputs=[target],
            ),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project, lookahead_depth=2)
        project.record_tool_success("start")
        project.record_tool_success("choose left")

        command = advisor.advise()

        self.assertEqual(command.options[0].tool_name, "middle")
        finish = command.options[0].continuations[0]
        self.assertEqual(finish.tool_name, "finish left")
        self.assertEqual(finish.missing_artifacts, ("late seed",))


class TestPartialCycle(unittest.TestCase):
    def test_cycle_returns_to_the_middle_without_an_iteration_reset(self):
        start = Artifact("start")
        draft = Artifact("draft")
        review = Artifact("review")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("setup", inputs=[start], outputs=[draft]),
            Tool("review", inputs=[draft], outputs=[review]),
            Tool("revise", inputs=[review], outputs=[draft]),
            Tool("publish", inputs=[review], outputs=[target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project)

        project.record_tool_success("setup")
        project.record_tool_success("review")
        command = advisor.advise()
        self.assertEqual(command.target_artifacts, ())
        self.assertEqual(
            [option.tool_name for option in command.options],
            ["revise", "publish"],
        )

        project.record_tool_success("revise")
        self.assertEqual(advisor.advise().options[0].tool_name, "review")

        project.record_tool_success("review")
        project.record_tool_success("publish")
        self.assertEqual(advisor.advise().status, "COMPLETE")

    def test_targets_can_be_accepted_or_the_cycle_can_continue(self):
        start = Artifact("start")
        draft = Artifact("draft")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("draft", inputs=[start], outputs=[draft]),
            Tool("evaluate", inputs=[draft], outputs=[start, target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project)
        user = User(project)
        project.record_tool_success("draft")
        project.record_tool_success("evaluate")

        command = advisor.advise()

        self.assertEqual(command.status, "COMMAND")
        self.assertEqual(command.target_artifacts, ("target",))
        self.assertTrue(command.target_acceptance_required)
        self.assertEqual(command.options[0].tool_name, "draft")

        project.record_tool_success("draft")
        self.assertEqual(advisor.advise().target_artifacts, ())

        project.record_tool_success("evaluate")
        user.accept_targets()
        self.assertEqual(advisor.advise().status, "COMPLETE")

    def test_targets_cannot_be_accepted_before_they_are_produced(self):
        start = Artifact("start")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("finish", inputs=[start], outputs=[target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project)
        User(project).accept_targets()

        with self.assertRaisesRegex(ValueError, "before they are produced"):
            advisor.advise()

    def test_linear_target_completes_without_acceptance(self):
        start = Artifact("start")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("finish", inputs=[start], outputs=[target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project)
        project.record_tool_success("finish")

        command = advisor.advise()

        self.assertEqual(command.status, "COMPLETE")
        self.assertEqual(command.options, ())

    def test_acceptance_depends_on_the_selected_target_route(self):
        start = Artifact("start")
        work = Artifact("work")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("start", inputs=[start], outputs=[work]),
            Tool("cyclic target", inputs=[work], outputs=[work, target]),
            Tool("linear target", inputs=[work], outputs=[target]),
            starting=["start"],
            target=["target"],
        )

        cyclic_project = Project(workflow)
        cyclic_advisor = Advisor(cyclic_project)
        cyclic_project.record_tool_success("start")
        cyclic_project.record_tool_success("cyclic target")

        cyclic_command = cyclic_advisor.advise()
        self.assertEqual(cyclic_command.status, "COMMAND")
        self.assertEqual(cyclic_command.target_artifacts, ("target",))
        self.assertTrue(cyclic_command.target_acceptance_required)

        linear_project = Project(workflow)
        linear_advisor = Advisor(linear_project)
        linear_project.record_tool_success("start")
        linear_project.record_tool_success("linear target")

        linear_command = linear_advisor.advise()
        self.assertEqual(linear_command.status, "COMPLETE")
        self.assertFalse(linear_command.target_acceptance_required)


class TestRecovery(unittest.TestCase):
    def setUp(self):
        start = Artifact("start")
        fork = Artifact("fork")
        target = Artifact("target")
        self.workflow = make_workflow(
            Tool("prepare", inputs=[start], outputs=[fork]),
            Tool("primary", inputs=[fork], outputs=[target]),
            Tool("backup", inputs=[fork], outputs=[target]),
            starting=["start"],
            target=["target"],
        )

    def test_retries_then_uses_a_sibling_option(self):
        project = Project(self.workflow)
        advisor = Advisor(project)
        project.record_tool_success("prepare")

        project.record_tool_failure("primary", "first failure")
        command = advisor.advise()

        self.assertEqual(command.status, "RECOVERY")
        self.assertEqual(command.options[0].tool_name, "primary")
        self.assertEqual(command.options[0].action, "RETRY")
        self.assertEqual(command.recovery.last_failed_tool, "primary")
        self.assertEqual(command.recovery.last_failure_reason, "first failure")

        project.record_tool_failure("primary", "retry failure")
        command = advisor.advise()

        self.assertEqual(command.status, "RECOVERY")
        self.assertEqual(command.options[0].tool_name, "backup")
        self.assertEqual(command.options[0].action, "ALTERNATIVE")
        self.assertEqual(
            command.recovery.exhausted_options,
            ("primary",),
        )

        project.record_tool_failure("backup", "first failure")
        self.assertEqual(advisor.advise().options[0].action, "RETRY")

        project.record_tool_success("backup")
        self.assertEqual(advisor.advise().status, "COMPLETE")

    def test_returns_blocked_after_every_option_and_retry_fail(self):
        project = Project(self.workflow)
        advisor = Advisor(project)
        project.record_tool_success("prepare")

        for tool_name in ("primary", "primary", "backup", "backup"):
            project.record_tool_failure(tool_name, "simulated failure")

        command = advisor.advise()

        self.assertEqual(command.status, "BLOCKED")
        self.assertEqual(command.options, ())
        self.assertEqual(command.recovery.last_failed_tool, "backup")

    def test_failed_continuation_rejects_the_old_target_candidate(self):
        start = Artifact("start")
        draft = Artifact("draft")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("write", inputs=[start], outputs=[draft]),
            Tool("evaluate", inputs=[draft], outputs=[start, target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project)
        project.record_tool_success("write")
        project.record_tool_success("evaluate")
        self.assertEqual(advisor.advise().target_artifacts, ("target",))

        project.record_tool_failure("write", "simulated failure")
        command = advisor.advise()

        self.assertEqual(command.status, "RECOVERY")
        self.assertEqual(command.target_artifacts, ())

        User(project).accept_targets()
        with self.assertRaisesRegex(ValueError, "before they are produced"):
            advisor.advise()

    def test_a_new_cycle_visit_receives_a_new_retry(self):
        start = Artifact("start")
        draft = Artifact("draft")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("write", inputs=[start], outputs=[draft]),
            Tool("evaluate", inputs=[draft], outputs=[start, target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project)
        project.record_tool_success("write")
        project.record_tool_success("evaluate")

        project.record_tool_failure("write", "first cycle failure")
        self.assertEqual(advisor.advise().options[0].action, "RETRY")
        project.record_tool_success("write")
        project.record_tool_success("evaluate")

        project.record_tool_failure("write", "second cycle failure")
        command = advisor.advise()

        self.assertEqual(command.status, "RECOVERY")
        self.assertEqual(command.options[0].action, "RETRY")


class TestRecoveryBacktracking(unittest.TestCase):
    def setUp(self):
        start = Artifact("start")
        after_a = Artifact("after A")
        after_b = Artifact("after B")
        supplied = Artifact("supplied")
        target = Artifact("target")
        self.workflow = make_workflow(
            Tool("A", inputs=[start], outputs=[after_a]),
            Tool("B", inputs=[after_a], outputs=[after_b]),
            Tool("C", inputs=[after_a, supplied], outputs=[target]),
            Tool("D", inputs=[after_a], outputs=[target]),
            Tool("E", inputs=[after_b], outputs=[target]),
            Tool("F", inputs=[after_b], outputs=[target]),
            starting=["start"],
            target=["target"],
        )

    def test_restores_the_nearest_earlier_decision(self):
        project = Project(self.workflow)
        advisor = Advisor(project)
        user = User(project)
        project.record_tool_success("A")
        project.record_tool_success("B")
        user.provide("supplied")

        for tool_name in ("E", "E", "F", "F"):
            project.record_tool_failure(tool_name, "simulated failure")

        command = advisor.advise()

        self.assertEqual(command.status, "RECOVERY")
        self.assertEqual(
            [option.tool_name for option in command.options],
            ["C", "D"],
        )
        self.assertEqual(
            [option.action for option in command.options],
            ["ALTERNATIVE", "ALTERNATIVE"],
        )
        self.assertEqual(command.recovery.backtrack_depth, 1)
        self.assertEqual(command.recovery.exhausted_options, ("B",))
        self.assertEqual(command.options[0].missing_artifacts, ())

        project.record_tool_success("C")
        self.assertEqual(advisor.advise().status, "COMPLETE")
        self.assertIn("B", project.state.successful_tools)
        self.assertEqual(
            project.state.failed_attempts,
            ("E", "E", "F", "F"),
        )


class TestAdviceReports(unittest.TestCase):
    def setUp(self):
        start = Artifact("start")
        target = Artifact("target")
        self.workflow = make_workflow(
            Tool("finish", inputs=[start], outputs=[target]),
            starting=["start"],
            target=["target"],
        )

    def test_advise_records_one_report_and_returns_updated_advice(self):
        project = Project(self.workflow)
        advisor = Advisor(project)

        first = advisor.advise()
        repeated = advisor.advise()
        self.assertEqual(first, repeated)
        self.assertEqual(project.events, ())

        command = advisor.advise(ArtifactAvailable("start"))
        self.assertEqual(
            project.events,
            (ArtifactAvailable("start"),),
        )
        self.assertEqual(command.options[0].missing_artifacts, ())

        command = advisor.advise(ToolSucceeded("finish"))
        self.assertEqual(command.status, "COMPLETE")
        self.assertEqual(
            project.events,
            (
                ArtifactAvailable("start"),
                ToolSucceeded("finish"),
            ),
        )

    def test_invalid_report_does_not_change_the_log(self):
        project = Project(self.workflow)
        advisor = Advisor(project)

        with self.assertRaisesRegex(ValueError, "visible root option"):
            advisor.advise(ToolSucceeded("unknown"))

        self.assertEqual(project.events, ())

        with self.assertRaisesRegex(ValueError, "Unknown artifact"):
            advisor.advise(ArtifactAvailable("unknown"))

        self.assertEqual(project.events, ())

    def test_rejects_an_unsupported_report_type(self):
        project = Project(self.workflow)
        advisor = Advisor(project)

        with self.assertRaisesRegex(TypeError, "project events"):
            advisor.advise("finish")  # type: ignore[arg-type]

        self.assertEqual(project.events, ())

    def test_rejects_a_tool_shown_only_in_the_preview(self):
        start = Artifact("start")
        middle = Artifact("middle")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("first", inputs=[start], outputs=[middle]),
            Tool("future", inputs=[middle], outputs=[target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project, lookahead_depth=2)

        self.assertEqual(
            advisor.advise().options[0].continuations[0].tool_name,
            "future",
        )
        with self.assertRaisesRegex(ValueError, "visible root option"):
            advisor.advise(ToolSucceeded("future"))

        self.assertEqual(project.events, ())


class TestLookahead(unittest.TestCase):
    def setUp(self):
        start = Artifact("start")
        first_output = Artifact("first output")
        second_output = Artifact("second output")
        target = Artifact("target")
        self.workflow = make_workflow(
            Tool("first", inputs=[start], outputs=[first_output]),
            Tool(
                "second",
                inputs=[first_output],
                outputs=[second_output],
            ),
            Tool("third", inputs=[second_output], outputs=[target]),
            starting=["start"],
            target=["target"],
        )

    def test_depth_one_shows_only_the_executable_root(self):
        command = Advisor(
            Project(self.workflow),
            lookahead_depth=1,
        ).advise()

        first = command.options[0]
        self.assertEqual(first.tool_name, "first")
        self.assertEqual(first.missing_artifacts, ("start",))
        self.assertEqual(first.continuations, ())
        self.assertTrue(first.has_more)
        self.assertEqual(first.outcome, "CONTINUE")

    def test_deeper_window_is_path_aware_and_reaches_the_target(self):
        command = Advisor(
            Project(self.workflow),
            lookahead_depth=3,
        ).advise()

        first = command.options[0]
        second = first.continuations[0]
        third = second.continuations[0]

        self.assertEqual(second.tool_name, "second")
        self.assertEqual(second.missing_artifacts, ())
        self.assertEqual(third.tool_name, "third")
        self.assertEqual(third.missing_artifacts, ())
        self.assertEqual(third.outcome, "COMPLETE")
        self.assertFalse(third.has_more)

    def test_middle_cycle_is_unfolded_only_to_the_selected_depth(self):
        start = Artifact("start")
        draft = Artifact("draft")
        review = Artifact("review")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("setup", inputs=[start], outputs=[draft]),
            Tool("review", inputs=[draft], outputs=[review]),
            Tool("revise", inputs=[review], outputs=[draft]),
            Tool("publish", inputs=[review], outputs=[target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        project.record_tool_success("setup")
        project.record_tool_success("review")

        command = Advisor(project, lookahead_depth=3).advise()
        revise, publish = command.options
        next_review = revise.continuations[0]

        self.assertEqual(publish.outcome, "COMPLETE")
        self.assertEqual(next_review.tool_name, "review")
        self.assertEqual(
            [option.tool_name for option in next_review.continuations],
            ["revise", "publish"],
        )
        self.assertTrue(next_review.continuations[0].has_more)

    def test_target_cycle_preview_and_reported_acceptance(self):
        start = Artifact("start")
        draft = Artifact("draft")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("write", inputs=[start], outputs=[draft]),
            Tool("evaluate", inputs=[draft], outputs=[start, target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project, lookahead_depth=2)

        command = advisor.advise()
        evaluate = command.options[0].continuations[0]
        self.assertEqual(evaluate.outcome, "TARGETS_READY")
        self.assertTrue(evaluate.has_more)

        advisor.advise(ToolSucceeded("write"))
        command = advisor.advise(ToolSucceeded("evaluate"))
        self.assertTrue(command.target_acceptance_required)
        self.assertEqual(command.target_artifacts, ("target",))

        command = advisor.advise(TargetsAccepted())
        self.assertEqual(command.status, "COMPLETE")

    def test_preview_marks_a_route_that_cannot_reach_the_target(self):
        start = Artifact("start")
        fork = Artifact("fork")
        dead_output = Artifact("dead output")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("prepare", inputs=[start], outputs=[fork]),
            Tool("dead route", inputs=[fork], outputs=[dead_output]),
            Tool("finish", inputs=[fork], outputs=[target]),
            starting=["start"],
            target=["target"],
        )

        command = Advisor(
            Project(workflow),
            lookahead_depth=2,
        ).advise()

        dead_route, finish = command.options[0].continuations
        self.assertEqual(dead_route.outcome, "DEAD_END")
        self.assertEqual(finish.outcome, "COMPLETE")


class TestAdviceBreadth(unittest.TestCase):
    def setUp(self):
        start = Artifact("start")
        fork = Artifact("fork")
        target = Artifact("target")
        self.workflow = make_workflow(
            Tool("prepare", inputs=[start], outputs=[fork]),
            Tool("first route", inputs=[fork], outputs=[target]),
            Tool("second route", inputs=[fork], outputs=[target]),
            Tool("third route", inputs=[fork], outputs=[target]),
            starting=["start"],
            target=["target"],
        )

    def test_max_options_limits_each_visible_decision(self):
        project = Project(self.workflow)
        advisor = Advisor(
            project,
            lookahead_depth=2,
            max_options=1,
        )

        command = advisor.advise()
        prepare = command.options[0]
        self.assertFalse(command.options_truncated)
        self.assertEqual(
            [option.tool_name for option in prepare.continuations],
            ["first route"],
        )
        self.assertTrue(prepare.options_truncated)

        command = advisor.advise(ToolSucceeded("prepare"))
        self.assertEqual(
            [option.tool_name for option in command.options],
            ["first route"],
        )
        self.assertTrue(command.options_truncated)
        self.assertEqual(command, advisor.advise())

    def test_none_and_a_large_limit_return_every_option(self):
        for limit in (None, 5):
            project = Project(self.workflow)
            project.record_tool_success("prepare")
            command = Advisor(project, max_options=limit).advise()

            self.assertEqual(
                [option.tool_name for option in command.options],
                ["first route", "second route", "third route"],
            )
            self.assertFalse(command.options_truncated)

    def test_hidden_tool_report_is_rejected_without_changing_history(self):
        project = Project(self.workflow)
        project.record_tool_success("prepare")
        advisor = Advisor(project, max_options=1)
        original_events = project.events

        with self.assertRaisesRegex(ValueError, "visible root option"):
            advisor.advise(ToolSucceeded("second route"))

        self.assertEqual(project.events, original_events)

    def test_direct_history_is_not_invalidated_by_a_breadth_setting(self):
        project = Project(self.workflow)
        project.record_tool_success("prepare")
        project.record_tool_success("second route")

        command = Advisor(project, max_options=1).advise()

        self.assertEqual(command.status, "COMPLETE")

    def test_rejects_invalid_configuration(self):
        for value in (0, -1):
            with self.assertRaises(ValueError):
                Advisor(Project(self.workflow), lookahead_depth=value)
            with self.assertRaises(ValueError):
                Advisor(Project(self.workflow), max_options=value)

        for value in (True, 1.5, "2"):
            with self.assertRaises(TypeError):
                Advisor(Project(self.workflow), lookahead_depth=value)
            with self.assertRaises(TypeError):
                Advisor(Project(self.workflow), max_options=value)


class TestRecoveryBreadth(unittest.TestCase):
    def setUp(self):
        start = Artifact("start")
        fork = Artifact("fork")
        target = Artifact("target")
        self.workflow = make_workflow(
            Tool("prepare", inputs=[start], outputs=[fork]),
            Tool("primary", inputs=[fork], outputs=[target]),
            Tool("backup", inputs=[fork], outputs=[target]),
            Tool("third", inputs=[fork], outputs=[target]),
            starting=["start"],
            target=["target"],
        )

    def test_failure_returns_retry_and_untried_siblings(self):
        project = Project(self.workflow)
        advisor = Advisor(project, lookahead_depth=2)
        advisor.advise(ToolSucceeded("prepare"))

        command = advisor.advise(ToolFailed("primary", "failure"))

        self.assertEqual(command.status, "RECOVERY")
        self.assertEqual(
            [(option.tool_name, option.action) for option in command.options],
            [
                ("primary", "RETRY"),
                ("backup", "ALTERNATIVE"),
                ("third", "ALTERNATIVE"),
            ],
        )
        self.assertTrue(all(
            option.outcome == "COMPLETE"
            for option in command.options
        ))

    def test_each_once_failed_option_remains_a_retry(self):
        project = Project(self.workflow)
        advisor = Advisor(project)
        advisor.advise(ToolSucceeded("prepare"))
        advisor.advise(ToolFailed("primary"))

        command = advisor.advise(ToolFailed("backup"))

        self.assertEqual(
            [(option.tool_name, option.action) for option in command.options],
            [
                ("backup", "RETRY"),
                ("primary", "RETRY"),
                ("third", "ALTERNATIVE"),
            ],
        )

    def test_max_one_recreates_retry_first_recovery(self):
        project = Project(self.workflow)
        advisor = Advisor(project, max_options=1)
        advisor.advise(ToolSucceeded("prepare"))

        command = advisor.advise(ToolFailed("primary"))
        self.assertEqual(command.options[0].tool_name, "primary")
        self.assertEqual(command.options[0].action, "RETRY")
        self.assertTrue(command.options_truncated)

        command = advisor.advise(ToolFailed("primary"))
        self.assertEqual(command.options[0].tool_name, "backup")
        self.assertEqual(command.options[0].action, "ALTERNATIVE")
        self.assertTrue(command.options_truncated)

    def test_earlier_decisions_stay_closed_while_siblings_remain(self):
        start = Artifact("start")
        after_start = Artifact("after start")
        branch_output = Artifact("branch output")
        target = Artifact("target")
        workflow = make_workflow(
            Tool("start", inputs=[start], outputs=[after_start]),
            Tool("branch", inputs=[after_start], outputs=[branch_output]),
            Tool("earlier alternative", inputs=[after_start], outputs=[target]),
            Tool("nested one", inputs=[branch_output], outputs=[target]),
            Tool("nested two", inputs=[branch_output], outputs=[target]),
            starting=["start"],
            target=["target"],
        )
        project = Project(workflow)
        advisor = Advisor(project)
        advisor.advise(ToolSucceeded("start"))
        advisor.advise(ToolSucceeded("branch"))

        command = advisor.advise(ToolFailed("nested one"))

        self.assertEqual(
            [option.tool_name for option in command.options],
            ["nested one", "nested two"],
        )
        self.assertNotIn(
            "earlier alternative",
            [option.tool_name for option in command.options],
        )


if __name__ == "__main__":
    unittest.main()
