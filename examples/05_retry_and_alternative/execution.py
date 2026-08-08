"""See a retry and a sibling alternative after a failure."""

from artifactflow import Advisor, Project

from workflow import workflow


project = Project(workflow)
advisor = Advisor(
    project,
    lookahead_depth=2,
    max_options=None,
)

command = advisor.advise()
for artifact_name in command.options[0].missing_artifacts:
    project.record_artifact_available(artifact_name)
project.record_tool_success("Prepare")
command = advisor.advise()

print("Normal options:", tuple(option.tool_name for option in command.options))
print("Run: Primary method -> failure")
project.record_tool_failure("Primary method", "simulated failure")
command = advisor.advise()

print("\nAfter the first failure, the Advisor offers both:")
for option in command.options:
    print(" -", option.action, option.tool_name, "->", option.outcome)

print("Choose: RETRY Primary method -> failure")
project.record_tool_failure("Primary method", "simulated retry failure")
command = advisor.advise()

print("\nThe exhausted primary route disappears:")
for option in command.options:
    print(" -", option.action, option.tool_name)

print("Run: Backup method -> failure")
project.record_tool_failure("Backup method", "simulated failure")
command = advisor.advise()
print("Advisor says:", command.options[0].action, "Backup method")

print("Run: Backup method -> success on its retry")
project.record_tool_success("Backup method")
command = advisor.advise()
print(command.status + ":", command.message)
