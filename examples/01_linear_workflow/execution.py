"""Ask for one instruction at a time in a linear workflow."""

from artifactflow import (
    Advisor,
    ArtifactAvailable,
    Project,
    ToolSucceeded,
)

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project)

# The first call has no report because nothing has happened yet.
command = advisor.advise()
option = command.options[0]
print("Next tool:", option.tool_name)
print("Provide first:", option.missing_artifacts)

# The external artifacts were obtained, so report those observed facts.
for artifact_name in option.missing_artifacts:
    command = advisor.advise(ArtifactAvailable(artifact_name))

while command.status == "COMMAND":
    option = command.options[0]
    print(
        "Run:",
        option.tool_name,
        "| expected outcome:",
        option.outcome,
    )

    # An external caller ran the tool and observed that it succeeded.
    command = advisor.advise(ToolSucceeded(option.tool_name))

print(command.status + ":", command.message)
print("No target acceptance was needed for this linear workflow.")
