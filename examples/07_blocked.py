"""Exhaust every route and observe the final BLOCKED command."""

from artifactflow import Advisor, Artifact, Project, Tool, User, Workflow


request = Artifact("Request")
prepared = Artifact("Prepared request")
result = Artifact("Result")

prepare = Tool("Prepare", inputs=[request], outputs=[prepared])
primary = Tool("Primary method", inputs=[prepared], outputs=[result])
backup = Tool("Backup method", inputs=[prepared], outputs=[result])

workflow = Workflow()
for tool in (prepare, primary, backup):
    workflow.add_tool(tool)
workflow.starting_artifacts = ["Request"]
workflow.target_artifacts = ["Result"]

project = Project(workflow)
advisor = Advisor(project)
user = User(project)
user.provide(*advisor.bootstrap_artifacts)

project.record_tool_success("Prepare")

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
