"""Continue a target-producing cycle and accept its third candidate."""

from artifactflow import Advisor, Project

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project, lookahead_depth=2)

command = advisor.advise()
print("First tool:", command.options[0].tool_name)
print("Provide first:", command.options[0].missing_artifacts)
for artifact_name in command.options[0].missing_artifacts:
    project.record_artifact_available(artifact_name)
command = advisor.advise()

candidate_number = 0

while command.status == "COMMAND":
    if command.target_acceptance_required:
        candidate_number += 1
        print("\nCandidate", candidate_number, "of 3 is ready.")
        print("Target artifacts:", command.target_artifacts)

        if candidate_number == 3:
            print("The simulated user accepts this candidate.")
            project.record_target_acceptance()
            command = advisor.advise()
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

    project.record_tool_success(option.tool_name)
    command = advisor.advise()

print("\n" + command.status + ":", command.message)
