"""Provide every possible bootstrap artifact before starting."""

from artifactflow import Advisor, Project
from artifactflow.workflow.examples import workflow_1 as workflow


project = Project(
    workflow,
    starting_artifacts=["Artifact 1", "Artifact 3"],
    target_artifacts=["Artifact 5"],
)
advisor = Advisor(project)

print("All possible bootstrap:", advisor.bootstrap_artifacts)
print("Always needed:", advisor.mandatory_bootstrap_artifacts)
print("Route-dependent:", advisor.conditional_bootstrap_artifacts)

command = advisor.advise()
for artifact_name in advisor.bootstrap_artifacts:
    project.record_artifact_available(artifact_name)
command = advisor.advise()

target_attempt = 0
target_attempts_before_acceptance = 3
while command.status == "COMMAND":
    if command.target_artifacts:
        target_attempt += 1
        print(
            "Target candidate:",
            target_attempt,
            "of",
            target_attempts_before_acceptance,
        )

        if target_attempt == target_attempts_before_acceptance:
            print("Accept the target candidate.")
            project.record_target_acceptance()
            command = advisor.advise()
            continue

        print("Continue the target-producing cycle.")

    option = command.options[0]
    print("Use:", option.tool_name)
    project.record_tool_success(option.tool_name)
    command = advisor.advise()

print(command.message)
