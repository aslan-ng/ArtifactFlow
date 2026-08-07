"""Define a cycle that can repeatedly produce a target candidate."""

from artifactflow import Artifact, Tool, Workflow


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


if __name__ == "__main__":
    from pathlib import Path

    figure_path = Path(__file__).with_name("workflow.png")
    workflow.savefig(figure_path)
    print("Saved workflow figure:", figure_path)
