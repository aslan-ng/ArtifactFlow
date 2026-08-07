"""Exhaust a nested branch, then restore an earlier decision point."""

from artifactflow import Advisor, Project, User

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project)
user = User(project)

print("Always needed:", advisor.mandatory_bootstrap_artifacts)
print("Needed only on some routes:", advisor.conditional_bootstrap_artifacts)

command = advisor.advise()
user.provide(*command.options[0].required_artifacts)
print("Run: Prepare -> success")
project.record_tool_success("Prepare")

command = advisor.advise()
print(
    "Decision after Prepare:",
    tuple(option.tool_name for option in command.options),
)
print("Choose: Detailed route -> success")
project.record_tool_success("Detailed route")

# Both detailed engines fail once and fail again on their retries. This
# exhausts the detailed branch and returns to the earlier route choice.
failed_attempts = (
    "Detailed engine one",
    "Detailed engine one",
    "Detailed engine two",
    "Detailed engine two",
)

for failed_tool in failed_attempts:
    command = advisor.advise()
    chosen_option = next(
        option
        for option in command.options
        if option.tool_name == failed_tool
    )
    print(command.status + ":", chosen_option.action, failed_tool, "-> failure")
    project.record_tool_failure(failed_tool, "simulated failure")

command = advisor.advise()
print("The detailed branch is exhausted.")
assert command.recovery is not None
print("Backtrack depth:", command.recovery.backtrack_depth)
print("Exhausted earlier choice:", command.recovery.exhausted_options)
print(
    "Restored alternatives:",
    tuple(option.tool_name for option in command.options),
)
print(
    "Detailed route is still recorded as successful history:",
    "Detailed route" in project.state.successful_tools,
)

chosen_option = next(
    option
    for option in command.options
    if option.tool_name == "Concise route"
)
print("Concise route now needs:", chosen_option.required_artifacts)
user.provide(*chosen_option.required_artifacts)
print("Run: Concise route -> success")
project.record_tool_success("Concise route")

command = advisor.advise()
print(command.status + ":", command.message)
