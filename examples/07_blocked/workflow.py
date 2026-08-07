"""Define a workflow whose alternative routes may all fail."""

from artifactflow import Artifact, Tool, Workflow


request = Artifact("Request")
prepared = Artifact("Prepared request")
result = Artifact("Result")

prepare = Tool("Prepare", inputs=[request], outputs=[prepared])
primary = Tool("Primary method", inputs=[prepared], outputs=[result])
backup = Tool("Backup method", inputs=[prepared], outputs=[result])

workflow = Workflow()
for tool in (prepare, primary, backup):
    workflow.add_tool(tool)
workflow.starting_artifacts = ["Request"]
workflow.target_artifacts = ["Result"]


if __name__ == "__main__":
    from pathlib import Path

    figure_path = Path(__file__).with_name("workflow.png")
    workflow.savefig(figure_path)
    print("Saved workflow figure:", figure_path)
