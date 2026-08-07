"""Choose a route and provide only the bootstrap that route needs."""

from artifactflow import Advisor, Project, User

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project)
user = User(project)

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
    print(" -", option.tool_name, "needs", option.required_artifacts)

# The quick route is the only route that needs Template, so it is requested
# only after this example chooses that route.
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
