"""Ask for one instruction at a time in a linear workflow."""

from artifactflow import Advisor, Project

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project)

# The observer has not recorded any activity yet.
command = advisor.advise()
option = command.options[0]
print("Next tool:", option.tool_name)
print("Provide first:", option.missing_artifacts)

# These lines simulate an observer recording externally obtained artifacts.
for artifact_name in option.missing_artifacts:
    project.record_artifact_available(artifact_name)
command = advisor.advise()

while command.status == "COMMAND":
    option = command.options[0]
    print(
        "Run:",
        option.tool_name,
        "| expected outcome:",
        option.outcome,
    )

    # An observer records the result; the Advisor reads it afterward.
    project.record_tool_success(option.tool_name)
    command = advisor.advise()

print(command.status + ":", command.message)
print("No target acceptance was needed for this linear workflow.")
