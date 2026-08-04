from __future__ import annotations

from artifactflow.workflow.workflow import Workflow


EXECUTION_STATES = {
    "NOT_STARTED": "NOT_STARTED",
    "DONE": "DONE",
}

class Project:

    def __init__(
        self,
        workflow: Workflow,
        ready_artifacts: list[str] | None = None,
        starting_artifacts: list[str] | None = None,  # inherit from workflow when available
        target_artifacts: list[str] | None = None,  # inherit from workflow when available
    ):
        self.workflow = workflow
        self.starting_artifacts = (
            list(starting_artifacts)
            if starting_artifacts is not None
            else workflow.starting_artifacts
        )
        self.target_artifacts = (
            list(target_artifacts)
            if target_artifacts is not None
            else workflow.target_artifacts
        )
        self.states = {tool_name: EXECUTION_STATES["NOT STARTED"] for tool_name in self.tool_names}
        self.iteration = 1

    @property
    def tool_names(self):
        return self.workflow.tool_names

    @property
    def artifact_names(self):
        return self.workflow.artifact_names