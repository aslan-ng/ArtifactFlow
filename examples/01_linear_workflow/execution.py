"""Provide bootstrap artifacts first, then run a linear workflow."""

from artifactflow import Advisor, Project, User

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project)
user = User(project)

print("Bootstrap artifacts:", advisor.bootstrap_artifacts)
print("The user provides them before work begins.")
user.provide(*advisor.bootstrap_artifacts)

command = advisor.advise()
while command.status == "COMMAND":
    option = command.options[0]
    print("Run:", option.tool_name)

    # This records the observed result after an external caller runs the tool.
    project.record_tool_success(option.tool_name)
    command = advisor.advise()

print(command.status + ":", command.message)
