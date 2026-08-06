import unittest

from artifactflow.advisor import Advisor
from artifactflow.artifact.artifact import Artifact
from artifactflow.project import Project
from artifactflow.project.log import (
    ArtifactAvailable,
    Log,
    TargetsAccepted,
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
        log.targets_accepted()

        self.assertEqual(
            log.events,
            (
                ArtifactAvailable("A"),
                ToolSucceeded("first"),
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

    def test_advises_requirements_and_future_bootstrap(self):
        advisor = Advisor(Project(self.workflow))

        command = advisor.advise()

        self.assertEqual(command.status, "COMMAND")
        self.assertEqual(
            [option.tool_name for option in command.options],
            ["first"],
        )
        self.assertEqual(
            command.options[0].required_artifacts,
            ("A",),
        )
        self.assertEqual(command.suggested_artifacts, ("C",))

    def test_successful_tools_advance_the_advisor(self):
        project = Project(self.workflow)
        advisor = Advisor(project)

        project.record_tool_success("first")
        command = advisor.advise()

        self.assertEqual(command.options[0].tool_name, "second")
        self.assertEqual(
            command.options[0].required_artifacts,
            ("C",),
        )

        project.record_tool_success("second")
        project.record_tool_success("third")
        command = advisor.advise()

        self.assertEqual(command.status, "COMMAND")
        self.assertEqual(command.target_artifacts, ("result",))

        User(project).accept_targets()
        command = advisor.advise()

        self.assertEqual(command.status, "COMPLETE")
        self.assertEqual(command.target_artifacts, ("result",))
        self.assertIn("result", project.available_artifacts)

    def test_an_early_artifact_removes_its_suggestion_and_requirement(self):
        project = Project(self.workflow)
        advisor = Advisor(project)
        user = User(project)

        user.provide("C")
        command = advisor.advise()
        self.assertEqual(command.suggested_artifacts, ())

        project.record_tool_success("first")
        command = advisor.advise()
        self.assertEqual(command.options[0].required_artifacts, ())

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
            command.options[0].required_artifacts,
            ("left seed",),
        )
        self.assertEqual(command.options[1].required_artifacts, ())


class TestBootstrapSuggestionAfterRouteChoice(unittest.TestCase):
    def test_conditional_bootstrap_becomes_a_suggestion(self):
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
        advisor = Advisor(project)
        project.record_tool_success("start")
        project.record_tool_success("choose left")

        command = advisor.advise()

        self.assertEqual(command.options[0].tool_name, "middle")
        self.assertEqual(command.suggested_artifacts, ("late seed",))


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

        linear_project = Project(workflow)
        linear_advisor = Advisor(linear_project)
        linear_project.record_tool_success("start")
        linear_project.record_tool_success("linear target")

        self.assertEqual(linear_advisor.advise().status, "COMPLETE")


if __name__ == "__main__":
    unittest.main()
