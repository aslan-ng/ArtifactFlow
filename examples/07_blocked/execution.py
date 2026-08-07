"""Exhaust every route and observe the final BLOCKED command."""

from artifactflow import Advisor, Project, User

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project)
user = User(project)
user.provide(*advisor.bootstrap_artifacts)

project.record_tool_success("Prepare")

# Each route gets one initial attempt and one retry.
for failed_tool in (
    "Primary method",
    "Primary method",
    "Backup method",
    "Backup method",
):
    command = advisor.advise()
    option = next(
        option
        for option in command.options
        if option.tool_name == failed_tool
    )
    print(command.status + ":", option.action, failed_tool, "-> failure")
    project.record_tool_failure(failed_tool, "simulated failure")

command = advisor.advise()
print(command.status + ":", command.message)
print("Recorded failed attempts:", project.state.failed_attempts)
