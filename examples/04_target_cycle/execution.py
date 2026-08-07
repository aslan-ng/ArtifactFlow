"""Continue a target-producing cycle and accept its third candidate."""

from artifactflow import (
    Advisor,
    ArtifactAvailable,
    Project,
    TargetsAccepted,
    ToolSucceeded,
)

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project, lookahead_depth=2)

command = advisor.advise()
print("First tool:", command.options[0].tool_name)
print("Provide first:", command.options[0].missing_artifacts)
for artifact_name in command.options[0].missing_artifacts:
    command = advisor.advise(ArtifactAvailable(artifact_name))

candidate_number = 0

while command.status == "COMMAND":
    if command.target_acceptance_required:
        candidate_number += 1
        print("\nCandidate", candidate_number, "of 3 is ready.")
        print("Target artifacts:", command.target_artifacts)

        if candidate_number == 3:
            print("The simulated user accepts this candidate.")
            command = advisor.advise(TargetsAccepted())
            continue

        print("The candidate is not accepted; continue the cycle.")

    option = command.options[0]
    print("Run root tool:", option.tool_name, "| outcome:", option.outcome)

    for continuation in option.continuations:
        print(
            " Preview:",
            continuation.tool_name,
            "| outcome:",
            continuation.outcome,
            "| more beyond preview:",
            continuation.has_more,
        )

    command = advisor.advise(ToolSucceeded(option.tool_name))

print("\n" + command.status + ":", command.message)
