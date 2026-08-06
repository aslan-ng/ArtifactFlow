import unittest

from artifactflow.artifact.artifact import Artifact
from artifactflow.project.log import ArtifactAvailable, Log, ToolSucceeded
from artifactflow.project.project import Project
from artifactflow.tool.tool import Tool
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

        self.assertEqual(
            log.events,
            (ArtifactAvailable("A"), ToolSucceeded("first")),
        )


class TestProjectAdvisor(unittest.TestCase):
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
        project = Project(self.workflow)

        self.assertEqual(project.bootstrap_artifacts, ("A", "C"))
        self.assertEqual(
            project.mandatory_bootstrap_artifacts,
            ("A", "C"),
        )
        self.assertEqual(project.conditional_bootstrap_artifacts, ())

    def test_advises_requirements_and_future_bootstrap(self):
        project = Project(self.workflow)

        command = project.advise()

        self.assertEqual(command.status, "COMMAND")
        self.assertEqual(
            [option.tool_name for option in command.options],
            ["first"],
        )
        self.assertEqual(
            [
                requirement.artifact_name
                for requirement in command.options[0].required_artifacts
            ],
            ["A"],
        )
        self.assertEqual(
            [suggestion.artifact_name for suggestion in command.suggestions],
            ["C"],
        )

    def test_successful_tools_advance_the_advisor(self):
        project = Project(self.workflow)

        project.log.tool_succeeded("first")
        command = project.advise()

        self.assertEqual(command.options[0].tool_name, "second")
        self.assertEqual(
            command.options[0].required_artifacts[0].artifact_name,
            "C",
        )

        project.log.tool_succeeded("second")
        project.log.tool_succeeded("third")
        command = project.advise()

        self.assertEqual(command.status, "COMPLETE")
        self.assertEqual(command.target_artifacts, ("result",))
        self.assertIn("result", project.available_artifacts)

    def test_an_early_artifact_removes_its_suggestion_and_requirement(self):
        project = Project(self.workflow)

        project.log.artifact_available("C")
        command = project.advise()
        self.assertEqual(command.suggestions, ())

        project.log.tool_succeeded("first")
        command = project.advise()
        self.assertEqual(command.options[0].required_artifacts, ())

    def test_target_must_be_produced_not_merely_available(self):
        project = Project(self.workflow, ready_artifacts=["result"])

        self.assertEqual(project.advise().status, "COMMAND")

    def test_rejects_a_tool_that_was_not_an_option(self):
        project = Project(self.workflow)
        project.log.tool_succeeded("second")

        with self.assertRaisesRegex(ValueError, "not an advised option"):
            project.advise()


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
        project = Project(self.workflow)

        self.assertEqual(project.bootstrap_artifacts, ("start", "left seed"))
        self.assertEqual(project.mandatory_bootstrap_artifacts, ("start",))
        self.assertEqual(
            project.conditional_bootstrap_artifacts,
            ("left seed",),
        )

    def test_returns_route_options_with_local_requirements(self):
        project = Project(self.workflow)
        project.log.tool_succeeded("start")

        command = project.advise()

        self.assertEqual(
            [option.tool_name for option in command.options],
            ["left", "right"],
        )
        self.assertEqual(
            [
                requirement.artifact_name
                for requirement in command.options[0].required_artifacts
            ],
            ["left seed"],
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
        project.log.tool_succeeded("start")
        project.log.tool_succeeded("choose left")

        command = project.advise()

        self.assertEqual(command.options[0].tool_name, "middle")
        self.assertEqual(
            [suggestion.artifact_name for suggestion in command.suggestions],
            ["late seed"],
        )


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

        project.log.tool_succeeded("setup")
        project.log.tool_succeeded("review")
        self.assertEqual(
            [option.tool_name for option in project.advise().options],
            ["revise", "publish"],
        )

        project.log.tool_succeeded("revise")
        self.assertEqual(project.advise().options[0].tool_name, "review")

        project.log.tool_succeeded("review")
        project.log.tool_succeeded("publish")
        self.assertEqual(project.advise().status, "COMPLETE")


if __name__ == "__main__":
    unittest.main()
