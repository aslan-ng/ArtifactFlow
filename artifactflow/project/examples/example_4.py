"""Choose the cyclic route in a workflow that also has a linear route."""

from artifactflow import (
    Advisor,
    ArtifactAvailable,
    Project,
    TargetsAccepted,
    ToolSucceeded,
)
from artifactflow.workflow.examples import workflow_3 as workflow


project = Project(
    workflow,
    starting_artifacts=["Artifact 1", "Artifact 3"],
    target_artifacts=["Artifact 5"],
)
advisor = Advisor(project, lookahead_depth=2)

print("All possible bootstrap:", advisor.bootstrap_artifacts)
print("Always needed:", advisor.mandatory_bootstrap_artifacts)
print("Route-dependent:", advisor.conditional_bootstrap_artifacts)

target_attempt = 0
target_attempts_before_acceptance = 3
command = advisor.advise()

while command.status == "COMMAND":
    print("Options:", tuple(option.tool_name for option in command.options))

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
            command = advisor.advise(TargetsAccepted())
            continue

    option = command.options[0]
    for candidate in command.options:
        if candidate.tool_name == "Tool 2":
            option = candidate
            print("Choose the cyclic route instead of terminal Tool 4.")
            break

    if option.missing_artifacts:
        print("Provide for this route:", option.missing_artifacts)
        for artifact_name in option.missing_artifacts:
            command = advisor.advise(ArtifactAvailable(artifact_name))

    print("Use:", option.tool_name)
    command = advisor.advise(ToolSucceeded(option.tool_name))

print(command.message)
