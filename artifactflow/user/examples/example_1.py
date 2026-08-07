"""Accept the third target candidate in a refinement cycle."""

from artifactflow import Advisor, Project, ToolSucceeded, User
from artifactflow.workflow.examples import workflow_1 as workflow


project = Project(
    workflow,
    starting_artifacts=["Artifact 1", "Artifact 3"],
    target_artifacts=["Artifact 5"],
)
advisor = Advisor(project)
user = User(project)

user.provide(*advisor.bootstrap_artifacts)

target_attempt = 0
command = advisor.advise()

while command.status == "COMMAND":
    if command.target_artifacts:
        target_attempt += 1

        if target_attempt == 3:
            print("Accept candidate:", target_attempt)
            user.accept_targets()
            command = advisor.advise()
            continue

        print("Reject candidate:", target_attempt)

    option = command.options[0]
    print("Use:", option.tool_name)
    command = advisor.advise(ToolSucceeded(option.tool_name))

print(command.message)
