"""Choose a route, then provide only the bootstrap that route needs."""

from artifactflow import Advisor, Artifact, Project, Tool, User, Workflow


""" Setup """
request = Artifact("Request")
prepared_request = Artifact("Prepared request")
template = Artifact("Template")
custom_draft = Artifact("Custom draft")
report = Artifact("Report")

prepare = Tool("Prepare request", inputs=[request], outputs=[prepared_request])
quick = Tool(
    "Quick route",
    inputs=[prepared_request, template],
    outputs=[report],
)
custom = Tool(
    "Custom route",
    inputs=[prepared_request],
    outputs=[custom_draft],
)
finish_custom = Tool(
    "Finish custom route",
    inputs=[custom_draft],
    outputs=[report],
)

workflow = Workflow()
for tool in (prepare, quick, custom, finish_custom):
    workflow.add_tool(tool)
workflow.starting_artifacts = ["Request"]
workflow.target_artifacts = ["Report"]
#workflow.show()

project = Project(workflow)
advisor = Advisor(project)
user = User(project)

""" Execution """
print("Always needed:", advisor.mandatory_bootstrap_artifacts)
print("Needed only on some routes:", advisor.conditional_bootstrap_artifacts)

command = advisor.advise()
first_option = command.options[0]
print("Provide now:", first_option.required_artifacts)
user.provide(*first_option.required_artifacts)
print("Run:", first_option.tool_name)
project.record_tool_success(first_option.tool_name)

command = advisor.advise()
print("The Advisor now offers:")
for option in command.options:
    needed = option.required_artifacts
    print(" -", option.tool_name, "needs", needed)

chosen_option = next(
    option
    for option in command.options
    if option.tool_name == "Quick route"
)
print("Choose:", chosen_option.tool_name)
print("Provide for this route:", chosen_option.required_artifacts)
user.provide(*chosen_option.required_artifacts)
project.record_tool_success(chosen_option.tool_name)

command = advisor.advise()
print(command.status + ":", command.message)
