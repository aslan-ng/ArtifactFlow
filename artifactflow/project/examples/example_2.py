"""Provide bootstrap artifacts only when the chosen tool needs them."""

from artifactflow import Advisor, Project, User
from artifactflow.workflow.examples import workflow_1 as workflow


project = Project(
    workflow,
    starting_artifacts=["Artifact 1", "Artifact 3"],
    target_artifacts=["Artifact 5"],
)
advisor = Advisor(project)
user = User(project)

target_attempt = 0
target_attempts_before_acceptance = 3
command = advisor.advise()

while command.status == "COMMAND":
    print("Suggestions for later:", command.suggested_artifacts)
    print("Options:", command.options)

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
            user.accept_targets()
            command = advisor.advise()
            continue

        print("Continue the target-producing cycle.")

    option = command.options[0]
    if option.required_artifacts:
        print("Provide now:", option.required_artifacts)
        user.provide(*option.required_artifacts)

    print("Use:", option.tool_name)
    project.record_tool_success(option.tool_name)
    command = advisor.advise()

print(command.message)
