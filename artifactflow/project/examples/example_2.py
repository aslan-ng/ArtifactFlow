"""Obtain bootstrap artifacts only when the selected tool needs them."""

from artifactflow.project.project import Project
from artifactflow.workflow.examples import workflow_1 as workflow


workflow.show()

project = Project(
    workflow=workflow,
    starting_artifacts=["Artifact 1"],
    target_artifacts=["Artifact 5"],
)

command = project.advise()
while command.status == "COMMAND":
    print("Suggestions:", command.suggestions)
    print("Options:", command.options)

    option = command.options[0]
    for requirement in option.required_artifacts:
        # Obtain the artifact from the user. Other sources can be added later.
        project.log.artifact_available(requirement.artifact_name)

    # Run option.tool_name until success. The runtime then records the event.
    project.log.tool_succeeded(option.tool_name)
    command = project.advise()

print(command.message)
