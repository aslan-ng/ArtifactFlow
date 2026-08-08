"""Limit advice to one option, then exhaust every route."""

from artifactflow import Advisor, Project

from workflow import workflow


project = Project(workflow)
advisor = Advisor(
    project,
    lookahead_depth=1,
    max_options=1,
)

command = advisor.advise()
for artifact_name in command.options[0].missing_artifacts:
    project.record_artifact_available(artifact_name)
project.record_tool_success("Prepare")
command = advisor.advise()

print("Visible option:", command.options[0].tool_name)
print("Were other root options hidden?", command.options_truncated)

same_command = advisor.advise()
print(
    "Asking again while the log is unchanged returns the same option:",
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
    project.record_tool_failure(option.tool_name, "simulated failure")
    command = advisor.advise()

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
