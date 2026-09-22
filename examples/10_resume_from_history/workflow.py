"""
Define two review routes for the execution-history resume example.
"""

from artifactflow import Artifact, Tool, Workflow


brief = Artifact("Brief")
draft = Artifact("Draft")
approved_report = Artifact("Approved report")

write_draft = Tool(
    "Write draft",
    inputs=[brief],
    outputs=[draft],
)
automated_review = Tool(
    "Automated review",
    inputs=[draft],
    outputs=[approved_report],
)
human_review = Tool(
    "Human review",
    inputs=[draft],
    outputs=[approved_report],
)

workflow = Workflow()
for tool in (write_draft, automated_review, human_review):
    workflow.add_tool(tool)
workflow.starting_artifacts = ["Brief"]
workflow.target_artifacts = ["Approved report"]


if __name__ == "__main__":
    from pathlib import Path

    figure_path = Path(__file__).with_name("workflow.png")
    workflow.savefig(figure_path)
    print("Saved workflow figure:", figure_path)
