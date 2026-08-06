"""Prepare every possible bootstrap artifact before starting."""

from artifactflow.project.project import Project
from artifactflow.workflow.examples import workflow_1 as workflow


workflow.show()

project = Project(
    workflow=workflow,
    starting_artifacts=["Artifact 1", "Artifact 3"],
    target_artifacts=["Artifact 5"],
)

print("All possible bootstrap:", project.bootstrap_artifacts)
print("Always needed:", project.mandatory_bootstrap_artifacts)
print("Route-dependent:", project.conditional_bootstrap_artifacts)

for artifact_name in project.bootstrap_artifacts:
    project.log.artifact_available(artifact_name)

command = project.advise()
print(command)
while command.status == "COMMAND":
    option = command.options[0]
    print("Use:", option.tool_name)

    # The real tool runtime should add this event after the call succeeds.
    project.log.tool_succeeded(option.tool_name)
    command = project.advise()
    print(command)

print(command.message)
