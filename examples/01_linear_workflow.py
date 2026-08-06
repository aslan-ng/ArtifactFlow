"""
Provide bootstrap artifacts first, then complete a linear workflow.
"""

from artifactflow import Advisor, Artifact, Project, Tool, User, Workflow


""" Setup """
brief = Artifact("Brief")
outline = Artifact("Outline")
final_report = Artifact("Final report")

make_outline = Tool("Make outline", inputs=[brief], outputs=[outline])
write_report = Tool(
    "Write report",
    inputs=[outline],
    outputs=[final_report],
)

workflow = Workflow()
workflow.add_tool(make_outline)
workflow.add_tool(write_report)
workflow.starting_artifacts = ["Brief"]
workflow.target_artifacts = ["Final report"]
#workflow.show()

project = Project(workflow)
advisor = Advisor(project)
user = User(project)


""" Execution """
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
