"""Repeat a middle cycle until the third review, then publish.

The three-review rule is only a deterministic simulation. A real LLM or
human could decide whether to revise or publish by reading the review.
"""

from artifactflow import Advisor, Project, User

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project)
user = User(project)

review_number = 0
command = advisor.advise()

while command.status == "COMMAND":
    option_names = tuple(option.tool_name for option in command.options)
    print("Advisor offers:", option_names)

    # Most steps have one option. After each review, choose whether to repeat
    # the middle cycle or take its exit.
    if "Revise draft" in option_names and "Publish" in option_names:
        if review_number < 3:
            chosen_name = "Revise draft"
            print("Decision: the draft needs another revision.")
        else:
            chosen_name = "Publish"
            print("Decision: the draft is ready to publish.")
    else:
        chosen_name = option_names[0]

    chosen_option = next(
        option
        for option in command.options
        if option.tool_name == chosen_name
    )

    # Draft and Review are created by tools. Only the external Brief needs to
    # be provided when the Advisor first requests it.
    if chosen_option.required_artifacts:
        print("User provides:", chosen_option.required_artifacts)
        user.provide(*chosen_option.required_artifacts)

    print("Run:", chosen_option.tool_name)
    project.record_tool_success(chosen_option.tool_name)

    if chosen_option.tool_name == "Review draft":
        review_number += 1
        print("Completed review:", review_number, "of 3")

    command = advisor.advise()

print(command.status + ":", command.message)
print("No target acceptance was needed because Publish is a linear exit.")
