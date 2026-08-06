"""Continue a target-producing cycle and accept its third candidate."""

from artifactflow import Advisor, Artifact, Project, Tool, User, Workflow


brief = Artifact("Brief")
draft = Artifact("Draft")
candidate = Artifact("Candidate report")

write = Tool("Write draft", inputs=[brief], outputs=[draft])
evaluate = Tool(
    "Evaluate draft",
    inputs=[draft],
    outputs=[brief, candidate],
)

workflow = Workflow()
workflow.add_tool(write)
workflow.add_tool(evaluate)
workflow.starting_artifacts = ["Brief"]
workflow.target_artifacts = ["Candidate report"]

project = Project(workflow)
advisor = Advisor(project)
user = User(project)
user.provide(*advisor.bootstrap_artifacts)

candidate_number = 0
command = advisor.advise()

while command.status == "COMMAND":
    if command.target_artifacts:
        candidate_number += 1
        print("The cycle produced candidate", candidate_number, "of 3.")

        if candidate_number == 3:
            print("The simulated user accepts this candidate.")
            user.accept_targets()
            command = advisor.advise()
            continue

        print("The candidate is not accepted; continue the cycle.")

    option = command.options[0]
    print("Run:", option.tool_name)
    project.record_tool_success(option.tool_name)
    command = advisor.advise()

print(command.status + ":", command.message)
