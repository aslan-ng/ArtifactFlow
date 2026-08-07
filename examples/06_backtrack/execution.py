"""Exhaust a nested branch, then restore an earlier decision point."""

from artifactflow import (
    Advisor,
    ArtifactAvailable,
    Project,
    ToolFailed,
    ToolSucceeded,
)

from workflow import workflow


project = Project(workflow)
advisor = Advisor(
    project,
    lookahead_depth=2,
    max_options=None,
)

command = advisor.advise()
prepare = command.options[0]
print("After Prepare, the preview shows:")
for route in prepare.continuations:
    print(" -", route.tool_name, "may need", route.missing_artifacts)

for artifact_name in prepare.missing_artifacts:
    command = advisor.advise(ArtifactAvailable(artifact_name))
command = advisor.advise(ToolSucceeded("Prepare"))

print("\nExecutable route choices:")
for option in command.options:
    print(" -", option.tool_name, "needs", option.missing_artifacts)

print("Choose: Detailed route -> success")
command = advisor.advise(ToolSucceeded("Detailed route"))

# Both detailed engines fail once and fail again on their retries. The first
# failure also exposes the unchecked sibling engine as an alternative.
failed_attempts = (
    "Detailed engine one",
    "Detailed engine one",
    "Detailed engine two",
    "Detailed engine two",
)

for failed_tool in failed_attempts:
    chosen_option = next(
        option
        for option in command.options
        if option.tool_name == failed_tool
    )
    print(
        command.status + ":",
        chosen_option.action,
        failed_tool,
        "-> failure",
    )
    command = advisor.advise(
        ToolFailed(failed_tool, "simulated failure")
    )
    if command.status == "RECOVERY":
        print(
            " Advisor now offers:",
            tuple(
                (option.action, option.tool_name)
                for option in command.options
            ),
        )

print("\nThe detailed branch is exhausted.")
assert command.recovery is not None
print("Backtrack depth:", command.recovery.backtrack_depth)
print(
    "Restored alternatives:",
    tuple(option.tool_name for option in command.options),
)
print(
    "Detailed route remains in the factual history:",
    "Detailed route" in project.state.successful_tools,
)

chosen_option = next(
    option
    for option in command.options
    if option.tool_name == "Concise route"
)
print("Concise route now needs:", chosen_option.missing_artifacts)

for artifact_name in chosen_option.missing_artifacts:
    print("The user provides:", artifact_name)
    command = advisor.advise(ArtifactAvailable(artifact_name))

command = advisor.advise(ToolSucceeded("Concise route"))
print(command.status + ":", command.message)
