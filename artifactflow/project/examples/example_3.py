"""A linear workflow completes as soon as its target is produced."""

from artifactflow import Advisor, Project, User
from artifactflow.workflow.examples import workflow_2 as workflow


project = Project(
    workflow,
    starting_artifacts=["Artifact 1"],
    target_artifacts=["Artifact 5"],
)
advisor = Advisor(project)
user = User(project)

print("Bootstrap:", advisor.bootstrap_artifacts)

command = advisor.advise()
while command.status == "COMMAND":
    option = command.options[0]

    if option.required_artifacts:
        print("Provide:", option.required_artifacts)
        user.provide(*option.required_artifacts)

    print("Use:", option.tool_name)
    project.record_tool_success(option.tool_name)
    command = advisor.advise()

print(command.message)
