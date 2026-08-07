"""Repeat a middle cycle until the third review, then publish.

The three-review rule is only a deterministic simulation. A real LLM or
human could decide whether to revise or publish by reading the review.
"""

from artifactflow import (
    Advisor,
    ArtifactAvailable,
    Project,
    ToolSucceeded,
)

from workflow import workflow


project = Project(workflow)
advisor = Advisor(project, lookahead_depth=3)

command = advisor.advise()
print("First tool:", command.options[0].tool_name)
print("Provide first:", command.options[0].missing_artifacts)
for artifact_name in command.options[0].missing_artifacts:
    command = advisor.advise(ArtifactAvailable(artifact_name))

review_number = 0
cycle_preview_shown = False

while command.status == "COMMAND":
    option_names = tuple(option.tool_name for option in command.options)
    print("\nExecutable options:", option_names)

    if not cycle_preview_shown and (
        "Revise draft" in option_names
        and "Publish" in option_names
    ):
        revise_preview = next(
            option
            for option in command.options
            if option.tool_name == "Revise draft"
        )
        future_review = revise_preview.continuations[0]
        print("The depth-3 preview unfolds one more pass:")
        print(" ", revise_preview.tool_name, "->", future_review.tool_name)
        for future_choice in future_review.continuations:
            print(
                "   ->",
                future_choice.tool_name,
                "| outcome:",
                future_choice.outcome,
                "| more beyond preview:",
                future_choice.has_more,
            )
        cycle_preview_shown = True

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
    print("Run root tool:", chosen_option.tool_name)
    command = advisor.advise(ToolSucceeded(chosen_option.tool_name))

    if chosen_option.tool_name == "Review draft":
        review_number += 1
        print("Completed review:", review_number, "of 3")

print("\n" + command.status + ":", command.message)
print("No target acceptance was needed because Publish is a linear exit.")
