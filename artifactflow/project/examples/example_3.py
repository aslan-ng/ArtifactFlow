"""A linear workflow completes as soon as its target is produced."""

from artifactflow import Advisor, Project
from artifactflow.workflow.examples import workflow_2 as workflow


project = Project(
    workflow,
    starting_artifacts=["Artifact 1"],
    target_artifacts=["Artifact 5"],
)
advisor = Advisor(project)

print("Bootstrap:", advisor.bootstrap_artifacts)

command = advisor.advise()
while command.status == "COMMAND":
    option = command.options[0]

    if option.missing_artifacts:
        print("Provide:", option.missing_artifacts)
        for artifact_name in option.missing_artifacts:
            project.record_artifact_available(artifact_name)
        command = advisor.advise()

    print("Use:", option.tool_name)
    project.record_tool_success(option.tool_name)
    command = advisor.advise()

print(command.message)
