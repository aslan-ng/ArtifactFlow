"""See route-dependent needs before choosing a route."""

from artifactflow import Advisor, Project

from workflow import workflow


project = Project(workflow)
advisor = Advisor(
    project,
    lookahead_depth=3,
    max_options=5,
)

command = advisor.advise()
prepare = command.options[0]
print("Run now:", prepare.tool_name)
print("Provide now:", prepare.missing_artifacts)
print("Possible routes after it succeeds:")

for route in prepare.continuations:
    print(" -", route.tool_name, "may need", route.missing_artifacts)
    for later_step in route.continuations:
        print("   then", later_step.tool_name)

print("Template is visible early, but only on the Quick route.")

for artifact_name in prepare.missing_artifacts:
    project.record_artifact_available(artifact_name)
project.record_tool_success("Prepare request")
command = advisor.advise()

print("\nExecutable route choices:")
for option in command.options:
    print(" -", option.tool_name, "needs", option.missing_artifacts)

print("Requested maximum: 5; valid options returned:", len(command.options))
print("Were any root options hidden?", command.options_truncated)

chosen_option = next(
    option
    for option in command.options
    if option.tool_name == "Quick route"
)
print("Choose:", chosen_option.tool_name)

for artifact_name in chosen_option.missing_artifacts:
    print("The user provides:", artifact_name)
    project.record_artifact_available(artifact_name)

project.record_tool_success(chosen_option.tool_name)
command = advisor.advise()
print(command.status + ":", command.message)
