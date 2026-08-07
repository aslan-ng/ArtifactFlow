"""See a retry and a sibling alternative after a failure."""

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
for artifact_name in command.options[0].missing_artifacts:
    command = advisor.advise(ArtifactAvailable(artifact_name))
command = advisor.advise(ToolSucceeded("Prepare"))

print("Normal options:", tuple(option.tool_name for option in command.options))
print("Run: Primary method -> failure")
command = advisor.advise(
    ToolFailed("Primary method", "simulated failure")
)

print("\nAfter the first failure, the Advisor offers both:")
for option in command.options:
    print(" -", option.action, option.tool_name, "->", option.outcome)

print("Choose: RETRY Primary method -> failure")
command = advisor.advise(
    ToolFailed("Primary method", "simulated retry failure")
)

print("\nThe exhausted primary route disappears:")
for option in command.options:
    print(" -", option.action, option.tool_name)

print("Run: Backup method -> failure")
command = advisor.advise(
    ToolFailed("Backup method", "simulated failure")
)
print("Advisor says:", command.options[0].action, "Backup method")

print("Run: Backup method -> success on its retry")
command = advisor.advise(ToolSucceeded("Backup method"))
print(command.status + ":", command.message)
