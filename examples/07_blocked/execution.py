"""Limit advice to one option, then exhaust every route."""

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
    lookahead_depth=1,
    max_options=1,
)

command = advisor.advise()
for artifact_name in command.options[0].missing_artifacts:
    command = advisor.advise(ArtifactAvailable(artifact_name))
command = advisor.advise(ToolSucceeded("Prepare"))

print("Visible option:", command.options[0].tool_name)
print("Were other root options hidden?", command.options_truncated)

same_command = advisor.advise()
print(
    "Asking again without a report returns the same option:",
    same_command.options[0].tool_name,
)

# max_options=1 gives a strict retry-first sequence. A hidden alternative
# becomes visible after the earlier option and its retry are exhausted.
for attempt_number in range(1, 5):
    option = command.options[0]
    print(
        "Attempt",
        attempt_number,
        ":",
        option.action,
        option.tool_name,
        "-> failure",
    )
    command = advisor.advise(
        ToolFailed(option.tool_name, "simulated failure")
    )

    if command.status != "BLOCKED":
        print(
            " Next visible option:",
            command.options[0].action,
            command.options[0].tool_name,
            "| more hidden:",
            command.options_truncated,
        )

print("\n" + command.status + ":", command.message)
print("Recorded failed attempts:", project.state.failed_attempts)
