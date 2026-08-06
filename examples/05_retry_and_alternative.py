"""Retry a failed tool once, then move to its sibling alternative."""

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

command = advisor.advise()
print("Run:", command.options[0].tool_name, "-> success")
project.record_tool_success(command.options[0].tool_name)

command = advisor.advise()
print("Options:", tuple(option.tool_name for option in command.options))
print("Run: Primary method -> failure")
project.record_tool_failure("Primary method", "simulated failure")

command = advisor.advise()
print(command.status + ":", command.options[0].action, "Primary method")
print("Run: Primary method -> failure again")
project.record_tool_failure("Primary method", "simulated retry failure")

command = advisor.advise()
print(command.status + ":")
for option in command.options:
    print(" -", option.action, option.tool_name)

print("Run: Backup method -> failure")
project.record_tool_failure("Backup method", "simulated failure")

command = advisor.advise()
print(command.status + ":", command.options[0].action, "Backup method")
print("Run: Backup method -> success on its retry")
project.record_tool_success("Backup method")

command = advisor.advise()
print(command.status + ":", command.message)
