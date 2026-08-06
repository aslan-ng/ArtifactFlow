"""Choose the cyclic route in a workflow that also has a linear route."""

from artifactflow import Advisor, Project, User
from artifactflow.workflow.examples import workflow_3 as workflow


project = Project(
    workflow,
    starting_artifacts=["Artifact 1", "Artifact 3"],
    target_artifacts=["Artifact 5"],
)
advisor = Advisor(project)
user = User(project)

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
            user.accept_targets()
            command = advisor.advise()
            continue

    option = command.options[0]
    for candidate in command.options:
        if candidate.tool_name == "Tool 2":
            option = candidate
            print("Choose the cyclic route instead of terminal Tool 4.")
            break

    if option.required_artifacts:
        print("Provide for this route:", option.required_artifacts)
        user.provide(*option.required_artifacts)

    print("Use:", option.tool_name)
    project.record_tool_success(option.tool_name)
    command = advisor.advise()

print(command.message)
