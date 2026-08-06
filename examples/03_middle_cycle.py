"""Repeat a middle cycle three times, then take its linear exit."""

from artifactflow import Advisor, Artifact, Project, Tool, User, Workflow


brief = Artifact("Brief")
draft = Artifact("Draft")
review = Artifact("Review")
published = Artifact("Published report")

write = Tool("Write draft", inputs=[brief], outputs=[draft])
review_draft = Tool("Review draft", inputs=[draft], outputs=[review])
revise = Tool("Revise draft", inputs=[review], outputs=[draft])
publish = Tool("Publish", inputs=[review], outputs=[published])

workflow = Workflow()
for tool in (write, review_draft, revise, publish):
    workflow.add_tool(tool)
workflow.starting_artifacts = ["Brief"]
workflow.target_artifacts = ["Published report"]

project = Project(workflow)
advisor = Advisor(project)
user = User(project)

planned_tools = (
    "Write draft",
    "Review draft",
    "Revise draft",
    "Review draft",
    "Revise draft",
    "Review draft",
    "Publish",
)
review_number = 0

for chosen_name in planned_tools:
    command = advisor.advise()
    print("Options:", tuple(option.tool_name for option in command.options))

    chosen_option = next(
        option
        for option in command.options
        if option.tool_name == chosen_name
    )
    if chosen_option.required_artifacts:
        print("User provides:", chosen_option.required_artifacts)
        user.provide(*chosen_option.required_artifacts)

    print("Run:", chosen_option.tool_name)
    project.record_tool_success(chosen_option.tool_name)

    if chosen_name == "Review draft":
        review_number += 1
        print("Completed review", review_number, "of 3")

command = advisor.advise()
print(command.status + ":", command.message)
print("No target acceptance was needed because Publish is a linear exit.")
