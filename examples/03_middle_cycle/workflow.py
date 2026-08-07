"""Define a workflow with a revise-review cycle before publication."""

from artifactflow import Artifact, Tool, Workflow


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


if __name__ == "__main__":
    from pathlib import Path

    figure_path = Path(__file__).with_name("workflow.png")
    workflow.savefig(figure_path)
    print("Saved workflow figure:", figure_path)
