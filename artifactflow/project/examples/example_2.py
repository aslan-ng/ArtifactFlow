"""Provide bootstrap artifacts only when the chosen tool needs them."""

from artifactflow import (
    Advisor,
    ArtifactAvailable,
    Project,
    TargetsAccepted,
    ToolSucceeded,
)
from artifactflow.workflow.examples import workflow_1 as workflow


project = Project(
    workflow,
    starting_artifacts=["Artifact 1", "Artifact 3"],
    target_artifacts=["Artifact 5"],
)
advisor = Advisor(project, lookahead_depth=3)

target_attempt = 0
target_attempts_before_acceptance = 3
command = advisor.advise()

while command.status == "COMMAND":
    print("Executable options:")
    for current_option in command.options:
        print(
            " -",
            current_option.tool_name,
            "missing",
            current_option.missing_artifacts,
            "then",
            tuple(
                continuation.tool_name
                for continuation in current_option.continuations
            ),
        )

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

        print("Continue the target-producing cycle.")

    option = command.options[0]
    if option.missing_artifacts:
        print("Provide now:", option.missing_artifacts)
        for artifact_name in option.missing_artifacts:
            command = advisor.advise(ArtifactAvailable(artifact_name))

    print("Use:", option.tool_name)
    command = advisor.advise(ToolSucceeded(option.tool_name))

print(command.message)
