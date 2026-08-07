"""Continue a target-producing cycle and accept its third candidate."""

from artifactflow import Advisor, Project, User

from workflow import workflow


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
